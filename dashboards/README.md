# Dashboards

Grafana dashboard definitions. Deployed via the `grafana-dashboards` ConfigMap
in [infra/k8s/apps/grafana/dashboard-config.yaml](../infra/k8s/apps/grafana/dashboard-config.yaml)
(the JSON here is the same content, kept as the readable source of truth).

- `incident-timeline.json` - per-incident lifecycle state timeline plus a
  count-by-stage panel, fed by `services/api`'s `sentinel_incident_stage_level`
  and `sentinel_incidents_by_stage` Prometheus gauges.
- `mumbai-air-quality.json` - real-time and comparative air quality telemetry
  across 8 Mumbai stations aligned with UN SDG 3 (Target 3.9), fed by
  `sentinel_air_quality_aqi`, `sentinel_air_quality_pm25`, and `sentinel_air_quality_pm10`.
