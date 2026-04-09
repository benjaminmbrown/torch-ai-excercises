package ai.torch.nexus.connector;

import ai.torch.nexus.connector.model.IntelEventRequest;
import ai.torch.nexus.connector.model.IntelEventResponse;
import jakarta.validation.Valid;
import org.springframework.http.ResponseEntity;
import org.springframework.web.bind.annotation.*;

import java.util.List;
import java.util.UUID;

/**
 * Contract-first REST controller implementing the generated {@code IntelEventsApi} interface.
 * All request/response types are generated from {@code openapi.yaml} at build time.
 */
@RestController
@RequestMapping("/api/v1/intel/events")
public class IntelEventController {

    private final IntelEventService service;

    public IntelEventController(IntelEventService service) {
        this.service = service;
    }

    /** POST /api/v1/intel/events — ingest a new intelligence event (async, returns 202). */
    @PostMapping
    public ResponseEntity<IntelEventResponse> ingestEvent(
            @Valid @RequestBody IntelEventRequest request) {
        IntelEventResponse response = service.ingest(request);
        return ResponseEntity.accepted().body(response);
    }

    /** GET /api/v1/intel/events — list recent events with optional filters. */
    @GetMapping
    public ResponseEntity<List<IntelEventResponse>> listEvents(
            @RequestParam(required = false) String sourceType,
            @RequestParam(required = false) String threatTier,
            @RequestParam(defaultValue = "20") int limit) {
        return ResponseEntity.ok(service.list(sourceType, threatTier, limit));
    }

    /** GET /api/v1/intel/events/{eventId} — retrieve a single event. */
    @GetMapping("/{eventId}")
    public ResponseEntity<IntelEventResponse> getEvent(@PathVariable UUID eventId) {
        return service.findById(eventId)
                .map(ResponseEntity::ok)
                .orElse(ResponseEntity.notFound().build());
    }
}
