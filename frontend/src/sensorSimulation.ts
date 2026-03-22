import type { LiveFeedEvent, NitwReference } from './serviceX'

const POWER_FACTOR = 0.92

export const FRONTEND_SENSOR_INTERVAL_MS = 900

export function buildFrontendTelemetryPacket(
  nitwReference: NitwReference,
  currentReadings: Record<string, number>,
  tickIndex: number,
  timestamp: string,
): Extract<LiveFeedEvent, { type: 'telemetry_packet' }> {
  const updates = nitwReference.loads
    .filter((load) => load.is_active !== false)
    .map((load) => {
      const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
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
      const signalStrength = buildSignalStrength(signature, tickIndex, phase)

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
          streamId: `frontend-${String((signature % 9) + 1).padStart(2, '0')}`,
          source: 'frontend-simulator',
          packetIndex: tickIndex,
          loadId: load.id,
          buildingId: load.building_id,
          busId: load.bus_id,
        },
      }
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

function buildSignalStrength(signature: number, tickIndex: number, phase: number) {
  const baseline = -71 - (signature % 9)
  const wave = Math.sin(tickIndex / 3.9 + phase) * 4.2
  return Math.round(clamp(baseline + wave, -89, -57))
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
