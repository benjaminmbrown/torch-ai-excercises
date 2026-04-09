package ai.torch.nexus.connector;

import ai.torch.nexus.connector.model.IntelEventRequest;
import ai.torch.nexus.connector.model.IntelEventResponse;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.time.OffsetDateTime;
import java.util.*;
import java.util.concurrent.ConcurrentHashMap;

/**
 * Core service layer: validates, enriches, and persists intelligence events.
 *
 * <p>Delegates upstream forwarding to {@link NexusFeignClient} with
 * circuit-breaker fallback. Enrichment (threat tier classification,
 * entity extraction) mirrors the Python SIGINT adapter logic.
 */
@Service
public class IntelEventService {

    private static final Logger log = LoggerFactory.getLogger(IntelEventService.class);

    // In-memory store — swap for a JPA repository in production
    private final Map<UUID, IntelEventResponse> store = new ConcurrentHashMap<>();

    private final NexusFeignClient nexusClient;

    public IntelEventService(NexusFeignClient nexusClient) {
        this.nexusClient = nexusClient;
    }

    public IntelEventResponse ingest(IntelEventRequest request) {
        UUID eventId = UUID.randomUUID();
        String threatTier = classifyThreatTier(request.getRawContent());
        List<String> entities = extractEntities(request.getRawContent());

        IntelEventResponse response = new IntelEventResponse()
                .eventId(eventId.toString())
                .sourceType(request.getSourceType())
                .threatTier(IntelEventResponse.ThreatTierEnum.valueOf(threatTier))
                .classificationLevel(request.getClassificationLevel().getValue())
                .summary(summarize(request.getRawContent()))
                .entities(entities)
                .geoCoordinates(request.getGeoCoordinates())
                .ingestedAt(OffsetDateTime.now())
                .processingStatus(IntelEventResponse.ProcessingStatusEnum.ACCEPTED);

        store.put(eventId, response);
        log.info("Ingested event {} [{}/{}]", eventId, request.getSourceType(), threatTier);

        // Forward to upstream NEXUS platform (fire-and-forget, circuit-breaker guarded)
        try {
            nexusClient.forwardEvent(request);
        } catch (Exception ex) {
            log.warn("Upstream forward failed for {} — fallback active: {}", eventId, ex.getMessage());
        }

        return response;
    }

    public List<IntelEventResponse> list(String sourceType, String threatTier, int limit) {
        return store.values().stream()
                .filter(e -> sourceType == null
                        || e.getSourceType().getValue().equalsIgnoreCase(sourceType))
                .filter(e -> threatTier == null
                        || (e.getThreatTier() != null
                            && e.getThreatTier().getValue().equalsIgnoreCase(threatTier)))
                .sorted(Comparator.comparing(IntelEventResponse::getIngestedAt).reversed())
                .limit(limit)
                .toList();
    }

    public Optional<IntelEventResponse> findById(UUID eventId) {
        return Optional.ofNullable(store.get(eventId));
    }

    // ------------------------------------------------------------------
    // Enrichment helpers (mirrors Python sigint.py logic)
    // ------------------------------------------------------------------

    private static String classifyThreatTier(String content) {
        if (content == null) return "ROUTINE";
        String upper = content.toUpperCase();
        if (upper.contains("FLASH"))     return "FLASH";
        if (upper.contains("IMMEDIATE")) return "IMMEDIATE";
        if (upper.contains("PRIORITY"))  return "PRIORITY";
        return "ROUTINE";
    }

    private static List<String> extractEntities(String content) {
        if (content == null) return List.of();
        // Simplified NER: extract tokens that look like proper nouns (all-caps, 2-8 chars)
        List<String> entities = new ArrayList<>();
        for (String token : content.split("\\s+")) {
            String clean = token.replaceAll("[^A-Z]", "");
            if (clean.length() >= 2 && clean.length() <= 8 && clean.equals(token.replaceAll("[^A-Z]", ""))) {
                entities.add(clean);
            }
        }
        return entities.stream().distinct().limit(10).toList();
    }

    private static String summarize(String content) {
        if (content == null || content.isBlank()) return "";
        // Truncate to first sentence or 120 chars for the summary field
        int end = content.indexOf('.');
        String first = end > 0 ? content.substring(0, end + 1) : content;
        return first.length() > 120 ? first.substring(0, 117) + "..." : first;
    }
}
