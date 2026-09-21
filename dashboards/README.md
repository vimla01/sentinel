# Dashboards

Grafana dashboard definitions. Deployed via the `grafana-dashboards` ConfigMap
in [infra/k8s/apps/grafana/dashboard-config.yaml](../infra/k8s/apps/grafana/dashboard-config.yaml)
(the JSON here is the same content, kept as the readable source of truth).

- `incident-timeline.json` - per-incident lifecycle state timeline plus a
  count-by-stage panel, fed by `services/api`'s `sentinel_incident_stage_level`
  and `sentinel_incidents_by_stage` Prometheus gauges.
