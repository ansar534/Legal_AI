# New resources (not imported): Container Insights log ingestion, the 5xx
# log-based metric/alert, and the dashboard.
resource "azurerm_log_analytics_workspace" "main" {
  name                = "law-legalai"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  sku                 = "PerGB2018"
  # Minimum retention: this is a student-credit subscription and the
  # workspace only needs to cover the grading window.
  retention_in_days = 30
}

resource "azurerm_monitor_action_group" "main" {
  name                = "ag-legalai-5xx"
  resource_group_name = azurerm_resource_group.main.name
  short_name          = "legalai5xx"

  dynamic "email_receiver" {
    for_each = var.alert_emails
    content {
      name                    = replace(replace(split("@", email_receiver.value)[0], ".", "-"), "_", "-")
      email_address           = email_receiver.value
      use_common_alert_schema = true
    }
  }
}

# Log-based metric: return one row per 5xx JSON log line. Do NOT summarize —
# `summarize count()` always returns a row (even when count is 0), which keeps
# a Count>0 alert permanently Fired so Azure never re-notifies. Matching rows
# only exist when real 5xx logs are present, so the alert can resolve and fire
# again (and email) on each new incident.
# AKS Container Insights here writes stdout into ContainerLog.LogEntry.
locals {
  http_5xx_query = <<-KQL
    ContainerLog
    | extend parsed = parse_json(LogEntry)
    | extend status_code = toint(parsed.status_code)
    | where status_code >= 500
    | project TimeGenerated, LogEntry
  KQL
}

resource "azurerm_monitor_scheduled_query_rules_alert_v2" "http_5xx" {
  name                = "alert-legalai-5xx"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location

  evaluation_frequency = "PT5M"
  window_duration      = "PT5M"
  scopes               = [azurerm_log_analytics_workspace.main.id]
  severity             = 2

  criteria {
    query                   = local.http_5xx_query
    time_aggregation_method = "Count"
    threshold               = 0
    operator                = "GreaterThan"

    failing_periods {
      minimum_failing_periods_to_trigger_alert = 1
      number_of_evaluation_periods             = 1
    }
  }

  action {
    action_groups = [azurerm_monitor_action_group.main.id]
  }

  auto_mitigation_enabled = true
  description             = "Fires when the app logs any HTTP 5xx in a 5-minute window."
}

# Dashboard: 5xx trend (same query as the alert) + AKS pod CPU/memory from
# Container Insights, in one Azure Monitor Workbook.
resource "azurerm_application_insights_workbook" "dashboard" {
  name                = "a6f3f1b2-5e4d-4a1a-9b2a-5a2b7c1e4f00"
  resource_group_name = azurerm_resource_group.main.name
  location            = var.location
  display_name        = "Legal AI Hub — Errors & Resource Usage"
  # Workbook API requires a lowercase resource id.
  source_id = lower(azurerm_log_analytics_workspace.main.id)

  data_json = jsonencode({
    version = "Notebook/1.0"
    items = [
      {
        type = 1
        content = {
          json = "## Legal AI Hub — Milestone 6 Dashboard\nHTTP 5xx log-based metric and AKS pod resource usage."
        }
      },
      {
        type = 3
        content = {
          version       = "KqlItem/1.0"
          query         = <<-KQL
            ContainerLog
            | extend parsed = parse_json(LogEntry)
            | extend status_code = toint(parsed.status_code)
            | where status_code >= 500
            | summarize ["5xx count"] = count() by bin(TimeGenerated, 5m)
            | order by TimeGenerated asc
          KQL
          size          = 0
          queryType     = 0
          resourceType  = "microsoft.operationalinsights/workspaces"
          visualization = "timechart"
        }
      },
      {
        type = 3
        content = {
          version       = "KqlItem/1.0"
          query         = <<-KQL
            Perf
            | where ObjectName == "K8SContainer" and CounterName in ("cpuUsageNanoCores", "memoryWorkingSetBytes")
            | where InstanceName has "legal-ai-hub"
            | summarize avg(CounterValue) by bin(TimeGenerated, 5m), CounterName
            | order by TimeGenerated asc
          KQL
          size          = 0
          queryType     = 0
          resourceType  = "microsoft.operationalinsights/workspaces"
          visualization = "timechart"
        }
      }
    ]
  })
}
