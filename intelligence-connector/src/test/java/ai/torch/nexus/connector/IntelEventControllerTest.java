package ai.torch.nexus.connector;

import com.fasterxml.jackson.databind.ObjectMapper;
import com.github.tomakehurst.wiremock.WireMockServer;
import com.github.tomakehurst.wiremock.core.WireMockConfiguration;
import org.junit.jupiter.api.*;
import org.springframework.beans.factory.annotation.Autowired;
import org.springframework.boot.test.autoconfigure.web.servlet.AutoConfigureMockMvc;
import org.springframework.boot.test.context.SpringBootTest;
import org.springframework.http.MediaType;
import org.springframework.test.context.DynamicPropertyRegistry;
import org.springframework.test.context.DynamicPropertySource;
import org.springframework.test.web.servlet.MockMvc;

import java.util.Map;

import static com.github.tomakehurst.wiremock.client.WireMock.*;
import static org.hamcrest.Matchers.*;
import static org.springframework.test.web.servlet.request.MockMvcRequestBuilders.*;
import static org.springframework.test.web.servlet.result.MockMvcResultMatchers.*;

@SpringBootTest(webEnvironment = SpringBootTest.WebEnvironment.RANDOM_PORT)
@AutoConfigureMockMvc
class IntelEventControllerTest {

    static WireMockServer wireMock = new WireMockServer(
            WireMockConfiguration.options().dynamicPort());

    @DynamicPropertySource
    static void configureNexusUrl(DynamicPropertyRegistry registry) {
        registry.add("nexus.platform.url", wireMock::baseUrl);
    }

    @BeforeAll
    static void startWireMock() {
        wireMock.start();
    }

    @AfterAll
    static void stopWireMock() {
        wireMock.stop();
    }

    @BeforeEach
    void resetStubs() {
        wireMock.resetAll();
    }

    @Autowired MockMvc mvc;
    @Autowired ObjectMapper mapper;

    // ------------------------------------------------------------------
    // Happy-path: upstream available
    // ------------------------------------------------------------------

    @Test
    @DisplayName("POST /intel/events — returns 202 with eventId and ACCEPTED status")
    void ingestEvent_returns202() throws Exception {
        wireMock.stubFor(post(urlEqualTo("/api/v1/intel/events"))
                .willReturn(aResponse().withStatus(202).withHeader("Content-Type", "application/json")
                        .withBody("{\"processingStatus\":\"ACCEPTED\"}")));

        String body = mapper.writeValueAsString(Map.of(
                "sourceType", "SIGINT",
                "rawContent", "FLASH — hostile SIGINT intercept at grid 38.5 / 27.3",
                "classificationLevel", "SECRET"
        ));

        mvc.perform(post("/api/v1/intel/events")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.eventId").isNotEmpty())
                .andExpect(jsonPath("$.processingStatus").value("ACCEPTED"))
                .andExpect(jsonPath("$.threatTier").value("FLASH"))
                .andExpect(jsonPath("$.sourceType").value("SIGINT"));
    }

    @Test
    @DisplayName("GET /intel/events — returns list, filterable by sourceType")
    void listEvents_filterBySourceType() throws Exception {
        // Seed one event
        String body = mapper.writeValueAsString(Map.of(
                "sourceType", "HUMINT",
                "rawContent", "HUMINT source reports PRIORITY movement near sector 7",
                "classificationLevel", "CONFIDENTIAL"
        ));
        wireMock.stubFor(post(anyUrl()).willReturn(aResponse().withStatus(202)
                .withHeader("Content-Type", "application/json")
                .withBody("{\"processingStatus\":\"ACCEPTED\"}")));

        mvc.perform(post("/api/v1/intel/events")
                .contentType(MediaType.APPLICATION_JSON).content(body));

        mvc.perform(get("/api/v1/intel/events").param("sourceType", "HUMINT"))
                .andExpect(status().isOk())
                .andExpect(jsonPath("$", hasSize(greaterThanOrEqualTo(1))))
                .andExpect(jsonPath("$[0].sourceType").value("HUMINT"));
    }

    @Test
    @DisplayName("GET /intel/events/{id} — 404 for unknown eventId")
    void getEvent_notFound() throws Exception {
        mvc.perform(get("/api/v1/intel/events/00000000-0000-0000-0000-000000000000"))
                .andExpect(status().isNotFound());
    }

    @Test
    @DisplayName("POST /intel/events — 400 when required fields missing")
    void ingestEvent_missingFields_returns400() throws Exception {
        mvc.perform(post("/api/v1/intel/events")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content("{}"))
                .andExpect(status().isBadRequest());
    }

    // ------------------------------------------------------------------
    // Circuit-breaker fallback
    // ------------------------------------------------------------------

    @Test
    @DisplayName("POST /intel/events — still returns 202 when upstream is down (fallback)")
    void ingestEvent_upstreamDown_fallbackActivates() throws Exception {
        wireMock.stubFor(post(anyUrl()).willReturn(aResponse().withStatus(503)));

        String body = mapper.writeValueAsString(Map.of(
                "sourceType", "OSINT",
                "rawContent", "ROUTINE open-source report on logistics convoy routes",
                "classificationLevel", "UNCLASSIFIED"
        ));

        mvc.perform(post("/api/v1/intel/events")
                        .contentType(MediaType.APPLICATION_JSON)
                        .content(body))
                .andExpect(status().isAccepted())
                .andExpect(jsonPath("$.eventId").isNotEmpty());
    }
}
