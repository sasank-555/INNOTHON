export type ModelSignalLabel = 'stable' | 'overload' | 'undervoltage' | 'sensor_fault' | 'outage'

export type ModelSensorInput = {
  id: string
  name: string
  expectedMw: number
  currentMw: number
  sensorIndex: number
  comparisonStatus: string | null
  reviewDecision: 'normal' | 'anomaly' | null
  status: string
}

export type ModelBuildingInput = {
  id: string
  name: string
  expectedMw: number
  currentMw: number
  sensors: ModelSensorInput[]
}

export type SensorHistoryPoint = {
  timestamp: string
  voltageV: number
  currentA: number
  powerMw: number
}

export type SensorModelInsight = {
  sensorId: string
  label: ModelSignalLabel
  anomalyScore: number
  confidence: number
  forecastMw: number
  currentVoltageV: number
  currentCurrentA: number
  reason: string
  windowStart: string
  windowEnd: string
  history: SensorHistoryPoint[]
}

export type BuildingModelInsight = {
  buildingId: string
  label: ModelSignalLabel
  anomalyScore: number
  confidence: number
  forecastMw: number
  highRiskSensorCount: number
  topIssue: string
  highlights: string[]
}

export type ModelOverview = {
  windowSize: number
  highRiskSensors: number
  atRiskBuildings: number
  averageAnomalyScore: number
  windowStart: string
  windowEnd: string
  source: 'synthetic-window'
}

export type ModelInsights = {
  sensors: Record<string, SensorModelInsight>
  buildings: Record<string, BuildingModelInsight>
  summary: ModelOverview
}

const WINDOW_SIZE = 6
const STEP_MINUTES = 5
const POWER_FACTOR = 0.92

export function buildPredictiveInsights(buildings: ModelBuildingInput[]): ModelInsights {
  const sensorInsights: Record<string, SensorModelInsight> = {}
  const buildingInsights: Record<string, BuildingModelInsight> = {}
  const windowEnd = new Date()
  const windowStart = new Date(windowEnd.getTime() - (WINDOW_SIZE - 1) * STEP_MINUTES * 60_000)
  let riskSensorCount = 0
  let riskScoreTotal = 0
  let buildingRiskCount = 0

  for (const building of buildings) {
    const buildingSensorInsights = building.sensors.map((sensor) => {
      const insight = buildSensorInsight(sensor, windowStart, windowEnd)
      sensorInsights[sensor.id] = insight
      if (insight.anomalyScore >= 0.55) {
        riskSensorCount += 1
      }
      riskScoreTotal += insight.anomalyScore
      return insight
    })

    const buildingInsight = buildBuildingInsight(building, buildingSensorInsights)
    buildingInsights[building.id] = buildingInsight
    if (buildingInsight.anomalyScore >= 0.55) {
      buildingRiskCount += 1
    }
  }

  return {
    sensors: sensorInsights,
    buildings: buildingInsights,
    summary: {
      windowSize: WINDOW_SIZE,
      highRiskSensors: riskSensorCount,
      atRiskBuildings: buildingRiskCount,
      averageAnomalyScore: buildings.length
        ? Number((riskScoreTotal / Math.max(Object.keys(sensorInsights).length, 1)).toFixed(3))
        : 0,
      windowStart: windowStart.toISOString(),
      windowEnd: windowEnd.toISOString(),
      source: 'synthetic-window',
    },
  }
}

function buildSensorInsight(
  sensor: ModelSensorInput,
  windowStart: Date,
  windowEnd: Date,
): SensorModelInsight {
  const label = inferLabel(sensor)
  const history = buildHistory(sensor, label, windowEnd)
  const currentPoint = history[history.length - 1]
  const previousPoints = history.slice(0, -1)
  const previousAverage =
    previousPoints.reduce((total, point) => total + point.powerMw, 0) / Math.max(previousPoints.length, 1)
  const forecastMw = clamp(currentPoint.powerMw + (currentPoint.powerMw - previousAverage) * 0.55, 0, Math.max(sensor.expectedMw * 2.8, 0.05))
  const anomalyScore = scoreLabel(label, sensor)
  const confidence = clamp(0.68 + anomalyScore * 0.28 + stableNoise(sensor.id, 0.0, 0.04), 0.72, 0.99)

  return {
    sensorId: sensor.id,
    label,
    anomalyScore,
    confidence,
    forecastMw: Number(forecastMw.toFixed(4)),
    currentVoltageV: Number(currentPoint.voltageV.toFixed(1)),
    currentCurrentA: Number(currentPoint.currentA.toFixed(2)),
    reason: buildReason(label, sensor, currentPoint.powerMw),
    windowStart: windowStart.toISOString(),
    windowEnd: windowEnd.toISOString(),
    history,
  }
}

function buildBuildingInsight(
  building: ModelBuildingInput,
  sensorInsights: SensorModelInsight[],
): BuildingModelInsight {
  const topSensor = [...sensorInsights].sort((left, right) => right.anomalyScore - left.anomalyScore)[0]
  const highRiskSensors = sensorInsights.filter((insight) => insight.anomalyScore >= 0.55)
  const forecastMw = sensorInsights.reduce((total, sensor) => total + sensor.forecastMw, 0)
  const anomalyScore = highRiskSensors.length
    ? Math.max(...highRiskSensors.map((sensor) => sensor.anomalyScore))
    : sensorInsights.length
      ? sensorInsights.reduce((total, sensor) => total + sensor.anomalyScore, 0) / sensorInsights.length
      : 0
  const label = topSensor?.label ?? 'stable'
  const confidence = topSensor?.confidence ?? 0.72
  const highlights = highRiskSensors.slice(0, 3).map((sensor) => {
    const displayName = sensor.sensorId.split('_').slice(-2).join(' ').toUpperCase()
    return `${displayName}: ${labelText(sensor.label)}`
  })

  return {
    buildingId: building.id,
    label,
    anomalyScore: Number(anomalyScore.toFixed(3)),
    confidence: Number(confidence.toFixed(3)),
    forecastMw: Number(forecastMw.toFixed(3)),
    highRiskSensorCount: highRiskSensors.length,
    topIssue: topSensor?.reason ?? 'Window is stable against the recent synthetic feed.',
    highlights,
  }
}

function buildHistory(
  sensor: ModelSensorInput,
  label: ModelSignalLabel,
  windowEnd: Date,
): SensorHistoryPoint[] {
  const checksum = stableNumber(sensor.id)
  const expectedMw = Math.max(sensor.expectedMw, 0.01)
  const currentMw = Math.max(sensor.currentMw || expectedMw, 0.005)
  const history: SensorHistoryPoint[] = []

  for (let index = 0; index < WINDOW_SIZE; index += 1) {
    const timestamp = new Date(windowEnd.getTime() - (WINDOW_SIZE - 1 - index) * STEP_MINUTES * 60_000)
    const progress = (index + 1) / WINDOW_SIZE
    const drift = (currentMw - expectedMw) * progress
    const oscillation = expectedMw * (0.015 * Math.sin((checksum % 7) + progress * Math.PI * 2))
    let powerMw = clamp(expectedMw + drift + oscillation, 0.002, Math.max(expectedMw * 2.6, 0.03))
    let voltageV = 406 + stableNoise(`${sensor.id}-${index}`, -8, 8)

    if (label === 'overload') {
      powerMw *= 1.18 + progress * 0.45
      voltageV = 388 + stableNoise(`${sensor.id}-ov-${index}`, -8, 12)
    } else if (label === 'undervoltage') {
      powerMw *= 0.96 + progress * 0.08
      voltageV = 350 + stableNoise(`${sensor.id}-uv-${index}`, -18, 14)
    } else if (label === 'sensor_fault') {
      const spike = index % 2 === 0 ? 1.9 : 0.45
      powerMw *= spike
      voltageV = 420 + stableNoise(`${sensor.id}-sf-${index}`, -120, 70)
    } else if (label === 'outage') {
      powerMw *= 0.14 - progress * 0.08
      voltageV = 40 + stableNoise(`${sensor.id}-ot-${index}`, -15, 20)
    }

    const currentA = computeCurrentA(powerMw, voltageV)
    history.push({
      timestamp: timestamp.toISOString(),
      voltageV: clamp(voltageV, 12, 490),
      currentA: Number(currentA.toFixed(2)),
      powerMw: Number(clamp(powerMw, 0, Math.max(expectedMw * 3.2, 0.04)).toFixed(4)),
    })
  }

  return history
}

function inferLabel(sensor: ModelSensorInput): ModelSignalLabel {
  if (sensor.reviewDecision === 'normal') {
    return 'stable'
  }

  if (sensor.comparisonStatus === 'missing_actual' || sensor.comparisonStatus === 'missing_expected') {
    return 'sensor_fault'
  }

  const ratio = sensor.expectedMw > 0 ? sensor.currentMw / sensor.expectedMw : 1
  if (sensor.comparisonStatus === 'deviation' && ratio < 0.32) {
    return 'outage'
  }
  if (sensor.comparisonStatus === 'deviation' && ratio > 1.2) {
    return 'overload'
  }
  if (sensor.comparisonStatus === 'deviation' && ratio < 0.82) {
    return 'undervoltage'
  }

  const checksum = stableNumber(sensor.id)
  if (sensor.reviewDecision === 'anomaly') {
    return checksum % 2 === 0 ? 'overload' : 'undervoltage'
  }
  if (checksum % 17 === 0) {
    return 'sensor_fault'
  }
  return 'stable'
}

function scoreLabel(label: ModelSignalLabel, sensor: ModelSensorInput) {
  const base = {
    stable: 0.18,
    overload: 0.81,
    undervoltage: 0.74,
    sensor_fault: 0.69,
    outage: 0.92,
  }[label]
  const deviationRatio = sensor.expectedMw > 0 ? Math.abs(sensor.currentMw - sensor.expectedMw) / sensor.expectedMw : 0
  const adjusted = base + Math.min(deviationRatio * 0.22, 0.18)
  return Number(clamp(adjusted, 0.12, 0.99).toFixed(3))
}

function buildReason(label: ModelSignalLabel, sensor: ModelSensorInput, powerMw: number) {
  const roundedPower = powerMw.toFixed(3)
  if (label === 'overload') return `Window trend shows sustained demand growth and projected feeder stress near ${roundedPower} MW.`
  if (label === 'undervoltage') return `Voltage profile softens across the window while demand stays active, suggesting undervoltage pressure.`
  if (label === 'sensor_fault') return `The recent signal pattern is inconsistent with neighboring steps, so the model suspects instrumentation noise or packet issues.`
  if (label === 'outage') return `Power collapses through the latest steps, which the model reads as an outage-like event.`
  return sensor.comparisonStatus === 'match'
    ? 'Recent history looks stable and aligned with the simulated operating envelope.'
    : 'Recent window remains inside a normal learned band despite short-term movement.'
}

function computeCurrentA(powerMw: number, voltageV: number) {
  return (powerMw * 1_000_000) / (Math.sqrt(3) * Math.max(voltageV, 1) * POWER_FACTOR)
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function stableNumber(value: string) {
  return Array.from(value).reduce((total, character, index) => total + character.charCodeAt(0) * (index + 1), 0)
}

function stableNoise(key: string, min: number, max: number) {
  const normalized = (stableNumber(key) % 1000) / 999
  return min + (max - min) * normalized
}

function labelText(label: ModelSignalLabel) {
  if (label === 'stable') return 'Stable'
  if (label === 'sensor_fault') return 'Sensor Fault'
  if (label === 'undervoltage') return 'Undervoltage'
  if (label === 'overload') return 'Overload'
  return 'Outage'
}
