const API_BASE_URL = import.meta.env.VITE_API_URL ?? 'http://127.0.0.1:8000'

type AuthPayload = {
  access_token: string
  token_type: string
  user: {
    id: string
    email: string
  }
}

export type DeviceRecord = {
  id: string
  hardwareId: string
  deviceModel: string
  displayName?: string
  networkName?: string
  nodeId?: string
  nodeKind?: string
  latitude?: number
  longitude?: number
  relayCount: number
  firmwareVersion?: string
  claimStatus: string
  claimCount: number
  sensorManifest: Array<{
    sensorId: string
    sensorType: string
    unit: string
    measurement?: string
    loadId?: string
    loadName?: string
    buildingId?: string
    busId?: string
  }>
  deviceAuthToken?: string
  latestReadings: Array<{
    sensorId: string
    sensorType: string
    value: number
    unit: string
    relayState?: string | null
    espTimestamp?: string | null
    serverReceivedAt: string
    metadata: Record<string, unknown>
  }>
}

export type NitwReference = {
  network: {
    name: string
    f_hz: number
    sn_mva: number
  }
  buses: Array<{
    id: string
    name?: string
    vn_kv?: number
    type?: string
  }>
  buildings?: Array<{
    id: string
    name: string
    bus_id: string
    lat: number
    long: number
    gateway_hardware_id?: string
    sensor_count?: number
    p_mw?: number
    q_mvar?: number
  }>
  external_grids?: Array<Record<string, unknown>>
  lines?: Array<Record<string, unknown>>
  loads: Array<{
    id: string
    name: string
    bus_id: string
    building_id?: string
    sensor_index?: number
    is_active?: boolean
    p_mw: number
    q_mvar: number
    lat: number
    long: number
  }>
  sensor_links: Array<{
    sensor_id: string
    element_type: string
    element_id: string
    measurement: string
  }>
}

export type NetworkBundle = {
  status: string
  network_name: string
  payload: NitwReference
  collections: Record<string, Array<Record<string, unknown>>>
  component_counts: Record<string, number>
}

export type CompareResponse = {
  status: string
  comparisons?: Array<{
    sensor_id: string
    element_type: string
    element_id: string
    measurement: string
    expected: number | null
    actual: number | null
    delta: number | null
    absolute_delta: number | null
    status: string
  }>
}

export type LiveFeedEvent =
  | {
      type: 'connection_ready'
      email: string
      serverTimestamp: string
    }
  | {
      type: 'telemetry_packet'
      hardwareId: string
      deviceId: string
      displayName?: string
      networkName?: string
      nodeKind?: string
      serverTimestamp: string
      espTimestamp?: string | null
      signalStrength?: number | null
      updates: Array<{
        sensorId: string
        sensorType: string
        value: number
        unit: string
        relayState?: string | null
        metadata: Record<string, unknown>
      }>
    }

export type TrainingReplayWindow = {
  status: string
  source: string
  dataset_path: string
  cursor: number
  next_cursor: number
  window_size: number
  window_start: string
  window_end: string
  step_seconds: number
  frame_count: number
  load_count: number
  frames: Array<{
    timestamp: string
    loads: Array<{
      load_id: string
      voltage_v: number
      current_a: number
      power_mw: number
      label: string
      is_anomaly: number
    }>
  }>
}

async function apiFetch<T>(path: string, init?: RequestInit, token?: string): Promise<T> {
  const headers = new Headers(init?.headers)
  if (!headers.has('Content-Type') && init?.body) {
    headers.set('Content-Type', 'application/json')
  }
  if (token) {
    headers.set('Authorization', `Bearer ${token}`)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, {
    ...init,
    headers,
  })

  if (!response.ok) {
    let message = `Request failed with status ${response.status}`
    try {
      const payload = (await response.json()) as { detail?: string }
      if (payload.detail) {
        message = payload.detail
      }
    } catch {
      // ignore parse failure and keep default message
    }
    throw new Error(message)
  }

  return response.json() as Promise<T>
}

export function registerUser(email: string, password: string): Promise<AuthPayload> {
  return apiFetch<AuthPayload>('/auth/register', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function loginUser(email: string, password: string): Promise<AuthPayload> {
  return apiFetch<AuthPayload>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ email, password }),
  })
}

export function fetchInventory(token: string): Promise<DeviceRecord[]> {
  return apiFetch<DeviceRecord[]>('/devices/inventory', undefined, token)
}

export function fetchClaimedDevices(token: string): Promise<DeviceRecord[]> {
  return apiFetch<DeviceRecord[]>('/devices', undefined, token)
}

export function claimDevice(token: string, hardwareId: string, manufacturerPassword: string): Promise<DeviceRecord> {
  return apiFetch<DeviceRecord>(
    '/devices/claim',
    {
      method: 'POST',
      body: JSON.stringify({ hardwareId, manufacturerPassword }),
    },
    token,
  )
}

export function fetchNitwReference(token: string): Promise<NitwReference> {
  return apiFetch<NitwReference>('/model/nitw-reference', undefined, token)
}

export function compareNitwNetwork(
  token: string,
  networkPayload: Record<string, unknown>,
  readingsPayload: Record<string, number>,
): Promise<CompareResponse> {
  return apiFetch<CompareResponse>(
    '/model/compare-network',
    {
      method: 'POST',
      body: JSON.stringify({
        network_payload: networkPayload,
        readings_payload: readingsPayload,
      }),
    },
    token,
  )
}

export function fetchTrainingReplayWindow(
  token: string,
  cursor?: number,
  windowSize?: number,
): Promise<TrainingReplayWindow> {
  const query = new URLSearchParams()
  if (typeof cursor === 'number') query.set('cursor', String(cursor))
  if (typeof windowSize === 'number') query.set('window_size', String(windowSize))
  const suffix = query.size ? `?${query.toString()}` : ''
  return apiFetch<TrainingReplayWindow>(`/model/training-replay-window${suffix}`, undefined, token)
}

export function syncNetwork(token: string, networkPayload: NitwReference): Promise<NetworkBundle> {
  return apiFetch<NetworkBundle>(
    '/networks/sync',
    {
      method: 'POST',
      body: JSON.stringify(networkPayload),
    },
    token,
  )
}

export function openLiveReadingsSocket(token: string): WebSocket {
  const url = new URL(API_BASE_URL)
  url.protocol = url.protocol === 'https:' ? 'wss:' : 'ws:'
  const basePath = url.pathname.endsWith('/') ? url.pathname.slice(0, -1) : url.pathname
  url.pathname = basePath ? `${basePath}/ws/live-readings` : '/ws/live-readings'
  url.search = ''
  url.searchParams.set('token', token)
  return new WebSocket(url.toString())
}
