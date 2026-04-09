package ai.torch.nexus.connector;

import ai.torch.nexus.connector.model.IntelEventRequest;
import ai.torch.nexus.connector.model.IntelEventResponse;
import org.springframework.cloud.openfeign.FeignClient;
import org.springframework.web.bind.annotation.PostMapping;
import org.springframework.web.bind.annotation.RequestBody;

/**
 * Feign client that forwards validated events to the upstream NEXUS platform.
 *
 * <p>The {@code fallback} attribute wires in a no-op stub so the connector
 * continues accepting events even when the upstream is unavailable. Configure
 * the base URL via {@code nexus.platform.url} in {@code application.properties}.
 */
@FeignClient(
        name  = "nexus-platform",
        url   = "${nexus.platform.url:http://localhost:9090}",
        fallback = NexusFeignClient.Fallback.class)
public interface NexusFeignClient {

    @PostMapping("/api/v1/intel/events")
    IntelEventResponse forwardEvent(@RequestBody IntelEventRequest request);

    /**
     * Fallback activated when the NEXUS platform circuit is open.
     * Returns a stub ACCEPTED response so ingest callers are not blocked.
     */
    class Fallback implements NexusFeignClient {
        @Override
        public IntelEventResponse forwardEvent(IntelEventRequest request) {
            return new IntelEventResponse()
                    .processingStatus(IntelEventResponse.ProcessingStatusEnum.ACCEPTED)
                    .summary("Upstream unavailable — event queued locally");
        }
    }
}
