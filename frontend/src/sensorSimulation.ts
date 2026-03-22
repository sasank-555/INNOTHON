import type { LiveFeedEvent, NitwReference, TrainingStreamTemplate } from './serviceX'

const POWER_FACTOR = 0.92

export const FRONTEND_SENSOR_INTERVAL_MS = 900
export const FILE_STREAM_LIMIT = 5

type SensorStreamAssignment = {
  streamId: string
  sourceLoadId: string
  cursor: number
  powerScale: number
  nominalVoltageV: number
  voltageBiasV: number
  points: TrainingStreamTemplate['points']
}

export type FrontendStreamRuntime = {
  bySensorId: Record<string, SensorStreamAssignment>
  streamCount: number
}

export function createFrontendStreamRuntime(
  nitwReference: NitwReference,
  templates: TrainingStreamTemplate[],
): FrontendStreamRuntime | null {
  if (!templates.length) return null

  const bySensorId: Record<string, SensorStreamAssignment> = {}

  for (const load of nitwReference.loads) {
    if (load.is_active === false) continue
    const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
    const template = templates[stableNumber(sensorId) % templates.length]
    const nominalPowerMw = average(template.points.map((point) => point.power_mw)) || 0.01
    const nominalVoltageV = average(template.points.map((point) => point.voltage_v)) || 19_800

    bySensorId[sensorId] = {
      streamId: template.stream_id,
      sourceLoadId: template.source_load_id,
      cursor: stableNumber(`${sensorId}:offset`) % Math.max(template.points.length, 1),
      powerScale: Math.max(load.p_mw, 0.01) / Math.max(nominalPowerMw, 0.001),
      nominalVoltageV,
      voltageBiasV: ((stableNumber(`${sensorId}:voltage`) % 21) - 10) * 1.8,
      points: template.points,
    }
  }

  return {
    bySensorId,
    streamCount: templates.length,
  }
}

export function buildFrontendTelemetryPacket(
  nitwReference: NitwReference,
  currentReadings: Record<string, number>,
  tickIndex: number,
  timestamp: string,
  runtime: FrontendStreamRuntime | null,
): Extract<LiveFeedEvent, { type: 'telemetry_packet' }> {
  if (!runtime || !Object.keys(runtime.bySensorId).length) {
    return buildSyntheticTelemetryPacket(nitwReference, currentReadings, tickIndex, timestamp)
  }

  const updates = nitwReference.loads
    .filter((load) => load.is_active !== false)
    .map((load) => {
      const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
      const assignment = runtime.bySensorId[sensorId]
      if (!assignment || !assignment.points.length) {
        return buildSyntheticUpdate(load, sensorId, currentReadings, tickIndex)
      }

      const point = assignment.points[assignment.cursor]
      assignment.cursor = (assignment.cursor + 1) % assignment.points.length
      const phase = stableNumber(sensorId) / 41
      const expectedMw = Math.max(load.p_mw, 0.01)
      const previousPowerMw = currentReadings[sensorId] ?? expectedMw
      const targetPowerMw = clamp(point.power_mw * assignment.powerScale, 0.001, Math.max(expectedMw * 3, 0.05))
      const blend = point.is_anomaly ? 0.72 : 0.48
      const powerMw = round(previousPowerMw * (1 - blend) + targetPowerMw * blend, 4)
      const normalizedVoltage = normalizeVoltage(point.voltage_v, assignment.nominalVoltageV)
      const label = point.is_anomaly ? mapFileLabel(point.label) : 'stable'
      const voltageV = round(applyVoltageMood(normalizedVoltage + assignment.voltageBiasV, label, tickIndex, phase), 1)
      const currentA = round((powerMw * 1_000_000) / (Math.sqrt(3) * Math.max(voltageV, 1) * POWER_FACTOR), 2)
      const signalStrength = buildSignalStrength(sensorId, tickIndex, phase)

      return {
        sensorId,
        sensorType: 'p_mw',
        value: powerMw,
        unit: 'MW',
        metadata: {
          powerMw,
          voltageV,
          currentA,
          signalStrength,
          label,
          isAnomaly: point.is_anomaly,
          simulated: true,
          streamId: assignment.streamId,
          sourceLoadId: assignment.sourceLoadId,
          source: 'csv-file-stream',
          templateTimestamp: point.timestamp,
          packetIndex: tickIndex,
          loadId: load.id,
          buildingId: load.building_id,
          busId: load.bus_id,
        },
      }
    })

  return {
    type: 'telemetry_packet',
    hardwareId: 'FRONTEND-FILE-SIM',
    deviceId: 'frontend-file-stream-simulator',
    displayName: 'Frontend File Stream Simulator',
    networkName: nitwReference.network.name,
    nodeKind: 'building',
    serverTimestamp: timestamp,
    signalStrength: null,
    updates,
  }
}

function buildSyntheticTelemetryPacket(
  nitwReference: NitwReference,
  currentReadings: Record<string, number>,
  tickIndex: number,
  timestamp: string,
): Extract<LiveFeedEvent, { type: 'telemetry_packet' }> {
  const updates = nitwReference.loads
    .filter((load) => load.is_active !== false)
    .map((load) => {
      const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
      return buildSyntheticUpdate(load, sensorId, currentReadings, tickIndex)
    })

  return {
    type: 'telemetry_packet',
    hardwareId: 'FRONTEND-SIM',
    deviceId: 'frontend-simulator',
    displayName: 'Frontend Sensor Simulator',
    networkName: nitwReference.network.name,
    nodeKind: 'building',
    serverTimestamp: timestamp,
    signalStrength: null,
    updates,
  }
}

function buildSyntheticUpdate(
  load: NitwReference['loads'][number],
  sensorId: string,
  currentReadings: Record<string, number>,
  tickIndex: number,
) {
  const expectedMw = Math.max(load.p_mw, 0.01)
  const signature = stableNumber(sensorId)
  const phase = signature / 37
  const label = classifySignal(signature, tickIndex)
  const previousPowerMw = currentReadings[sensorId] ?? expectedMw
  const baselineRatio = 1 + Math.sin(tickIndex / 3.1 + phase) * 0.035 + Math.cos(tickIndex / 5.7 + phase) * 0.018

  let targetRatio = baselineRatio
  if (label === 'overload') targetRatio = 1.22 + Math.sin(tickIndex / 2.4 + phase) * 0.05
  if (label === 'undervoltage') targetRatio = 0.76 + Math.sin(tickIndex / 2.9 + phase) * 0.04
  if (label === 'outage') targetRatio = 0.08 + Math.abs(Math.sin(tickIndex / 1.8 + phase)) * 0.03
  if (label === 'sensor_fault') targetRatio = 1 + Math.sin(tickIndex * 1.8 + phase) * 0.22

  const targetPowerMw = clamp(expectedMw * targetRatio, 0.001, Math.max(expectedMw * 2.4, 0.05))
  const blend = label === 'sensor_fault' ? 0.62 : 0.54
  const powerMw = round(previousPowerMw * (1 - blend) + targetPowerMw * blend, 4)
  const voltageV = round(buildVoltage(expectedMw, powerMw, tickIndex, phase, label), 1)
  const currentA = round((powerMw * 1_000_000) / (Math.sqrt(3) * Math.max(voltageV, 1) * POWER_FACTOR), 2)
  const signalStrength = buildSignalStrength(sensorId, tickIndex, phase)

  return {
    sensorId,
    sensorType: 'p_mw',
    value: powerMw,
    unit: 'MW',
    metadata: {
      powerMw,
      voltageV,
      currentA,
      signalStrength,
      label,
      isAnomaly: label === 'stable' ? 0 : 1,
      simulated: true,
      streamId: `frontend-${String((stableNumber(sensorId) % 9) + 1).padStart(2, '0')}`,
      source: 'frontend-synthetic-fallback',
      packetIndex: tickIndex,
      loadId: load.id,
      buildingId: load.building_id,
      busId: load.bus_id,
    },
  }
}

function mapFileLabel(label: string) {
  const normalized = label.trim().toLowerCase()
  if (normalized.includes('outage')) return 'outage'
  if (normalized.includes('overload')) return 'overload'
  if (normalized.includes('under')) return 'undervoltage'
  if (normalized.includes('fault') || normalized.includes('noise')) return 'sensor_fault'
  return 'watch'
}

function normalizeVoltage(rawVoltageV: number, nominalVoltageV: number) {
  return clamp((rawVoltageV / Math.max(nominalVoltageV, 1)) * 414, 95, 455)
}

function applyVoltageMood(voltageV: number, label: string, tickIndex: number, phase: number) {
  let nextVoltage = voltageV + Math.sin(tickIndex / 2.8 + phase) * 4.6
  if (label === 'overload') nextVoltage -= 18
  if (label === 'undervoltage') nextVoltage -= 36
  if (label === 'outage') nextVoltage -= 125
  if (label === 'sensor_fault') nextVoltage += Math.sin(tickIndex * 1.9 + phase) * 11
  if (label === 'watch') nextVoltage -= 10
  return clamp(nextVoltage, 95, 455)
}

function classifySignal(signature: number, tickIndex: number) {
  const cycle = (tickIndex + signature) % 72
  if (cycle === 0) return 'outage'
  if (cycle >= 12 && cycle <= 15) return 'overload'
  if (cycle >= 32 && cycle <= 36) return 'undervoltage'
  if (cycle >= 52 && cycle <= 55) return 'sensor_fault'
  return 'stable'
}

function buildVoltage(
  expectedMw: number,
  powerMw: number,
  tickIndex: number,
  phase: number,
  label: string,
) {
  const ratio = powerMw / Math.max(expectedMw, 0.01)
  let voltageV = 414 - (ratio - 1) * 34 + Math.sin(tickIndex / 2.5 + phase) * 4.8
  if (label === 'overload') voltageV -= 20
  if (label === 'undervoltage') voltageV -= 38
  if (label === 'outage') voltageV -= 125
  if (label === 'sensor_fault') voltageV += Math.sin(tickIndex * 2.1 + phase) * 12
  return clamp(voltageV, 95, 455)
}

function buildSignalStrength(sensorId: string, tickIndex: number, phase: number) {
  const signature = stableNumber(sensorId)
  const baseline = -71 - (signature % 9)
  const wave = Math.sin(tickIndex / 3.9 + phase) * 4.2
  return Math.round(clamp(baseline + wave, -89, -57))
}

function average(values: number[]) {
  return values.length ? values.reduce((total, value) => total + value, 0) / values.length : 0
}

function round(value: number, digits: number) {
  return Number(value.toFixed(digits))
}

function clamp(value: number, minimum: number, maximum: number) {
  return Math.min(maximum, Math.max(minimum, value))
}

function stableNumber(value: string) {
  return Array.from(value).reduce((total, character, index) => total + character.charCodeAt(0) * (index + 1), 0)
}
