import { api } from './client'

import type {
  MonitorNotificationDestination,
  MonitorNotificationDestinationTestResult,
  MonitorNotificationTemplateSet,
  RemoteMarketMonitorCheckRun,
  RemoteMarketMonitorOverview,
  RemoteMarketMonitorSettings,
  RemoteMarketMonitorTarget,
  RemoteMarketMonitorTargetUpdate,
} from '../types'

export async function fetchRemoteMarketMonitorOverview(): Promise<RemoteMarketMonitorOverview> {
  return (await api.get<RemoteMarketMonitorOverview>('/remote-market-monitor/overview')).data
}

export async function updateRemoteMarketMonitorTarget(
  sourceId: string,
  payload: RemoteMarketMonitorTargetUpdate,
): Promise<RemoteMarketMonitorTarget> {
  return (
    await api.patch<RemoteMarketMonitorTarget>(`/remote-market-monitor/targets/${sourceId}`, payload)
  ).data
}

export async function testRemoteMarketMonitorTarget(
  sourceId: string,
): Promise<RemoteMarketMonitorCheckRun> {
  return (
    await api.post<RemoteMarketMonitorCheckRun>(
      `/remote-market-monitor/targets/${sourceId}/test-query`,
    )
  ).data
}

export async function fetchRemoteMarketMonitorSettings(): Promise<RemoteMarketMonitorSettings> {
  return (await api.get<RemoteMarketMonitorSettings>('/system-settings/remote-market-monitor')).data
}

export async function updateRemoteMarketMonitorSettings(
  payload: RemoteMarketMonitorSettings,
): Promise<RemoteMarketMonitorSettings> {
  return (
    await api.patch<RemoteMarketMonitorSettings>('/system-settings/remote-market-monitor', payload)
  ).data
}

export async function fetchMonitorNotificationDestinations(): Promise<
  MonitorNotificationDestination[]
> {
  return (await api.get<MonitorNotificationDestination[]>('/system-settings/monitor-notification-destinations')).data
}

export async function createMonitorNotificationDestination(payload: {
  displayName: string
  enabled: boolean
  botToken: string
  chatId: string
  templateSetId: string
}): Promise<MonitorNotificationDestination> {
  return (
    await api.post<MonitorNotificationDestination>(
      '/system-settings/monitor-notification-destinations',
      payload,
    )
  ).data
}

export async function testMonitorNotificationDestination(
  destinationId: string,
  sourceId: string,
): Promise<MonitorNotificationDestinationTestResult> {
  return (
    await api.post<MonitorNotificationDestinationTestResult>(
      `/system-settings/monitor-notification-destinations/${destinationId}/test`,
      { sourceId },
    )
  ).data
}

export async function fetchMonitorNotificationTemplateSets(): Promise<
  MonitorNotificationTemplateSet[]
> {
  return (
    await api.get<MonitorNotificationTemplateSet[]>(
      '/system-settings/monitor-notification-template-sets',
    )
  ).data
}

export async function createMonitorNotificationTemplateSet(payload: {
  id: string
  displayName: string
  templates: Record<string, string>
}): Promise<MonitorNotificationTemplateSet> {
  return (
    await api.post<MonitorNotificationTemplateSet>(
      '/system-settings/monitor-notification-template-sets',
      payload,
    )
  ).data
}
