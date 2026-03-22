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
  signalStrengthDbm?: number | null
  simulated?: boolean
  simulatorLabel?: string | null
  anomalyFrame?: boolean
  streamId?: string | null
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
  source: 'synthetic-window' | 'live-window'
}

export type ModelInsights = {
  sensors: Record<string, SensorModelInsight>
  buildings: Record<string, BuildingModelInsight>
  summary: ModelOverview
}

const WINDOW_SIZE = 8
const FALLBACK_STEP_SECONDS = 3
const POWER_FACTOR = 0.92

export function buildPredictiveInsights(
  buildings: ModelBuildingInput[],
  sensorHistoryById: Record<string, SensorHistoryPoint[]> = {},
): ModelInsights {
  const sensorInsights: Record<string, SensorModelInsight> = {}
  const buildingInsights: Record<string, BuildingModelInsight> = {}
  const now = new Date()
  let riskSensorCount = 0
  let riskScoreTotal = 0
  let buildingRiskCount = 0
  let earliestWindowStart = now.toISOString()
  let latestWindowEnd = now.toISOString()
  let usingLiveWindow = false

  for (const building of buildings) {
    const buildingSensorInsights = building.sensors.map((sensor) => {
      const insight = buildSensorInsight(sensor, sensorHistoryById[sensor.id], now)
      sensorInsights[sensor.id] = insight
      if (insight.anomalyScore >= 0.55) {
        riskSensorCount += 1
      }
      if ((sensorHistoryById[sensor.id] ?? []).length > 1) {
        usingLiveWindow = true
      }
      riskScoreTotal += insight.anomalyScore
      if (insight.windowStart < earliestWindowStart) earliestWindowStart = insight.windowStart
      if (insight.windowEnd > latestWindowEnd) latestWindowEnd = insight.windowEnd
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
      windowStart: earliestWindowStart,
      windowEnd: latestWindowEnd,
      source: usingLiveWindow ? 'live-window' : 'synthetic-window',
    },
  }
}

function buildSensorInsight(
  sensor: ModelSensorInput,
  historyOverride: SensorHistoryPoint[] | undefined,
  windowEnd: Date,
): SensorModelInsight {
  const history = normalizeHistory(sensor, historyOverride, windowEnd)
  const currentPoint = history[history.length - 1]
  const earlierPoints = history.slice(0, Math.max(history.length - 3, 1))
  const recentPoints = history.slice(-3)
  const previousAverage = average(earlierPoints.map((point) => point.powerMw))
  const recentAverage = average(recentPoints.map((point) => point.powerMw))
  const trendMw = recentAverage - previousAverage
  const volatilityMw = computeVolatility(history.map((point) => point.powerMw))
  const expectedMw = Math.max(sensor.expectedMw, 0.01)
  const ratio = sensor.expectedMw > 0 ? currentPoint.powerMw / sensor.expectedMw : 1
  const label = inferLabel(sensor, currentPoint, ratio, trendMw, volatilityMw)
  const anomalyScore = scoreLabel(label, sensor, ratio, trendMw, volatilityMw, currentPoint)
  const forecastMw = clamp(
    currentPoint.powerMw + trendMw * 1.15 + volatilityMw * 0.28,
    0,
    Math.max(sensor.expectedMw * 3, 0.05),
  )
  const historyCoverage = Math.min(history.length / WINDOW_SIZE, 1)
  const deviationRatio = Math.abs(ratio - 1)
  const volatilityRatio = volatilityMw / expectedMw
  const trendRatio = Math.abs(trendMw) / expectedMw
  const livePulse = (Math.sin(windowEnd.getTime() / 3500 + stableNumber(sensor.id) / 29) + 1) / 2
  const confidence = clamp(
    0.56
      + historyCoverage * 0.12
      + anomalyScore * 0.16
      + Math.min(deviationRatio * 0.1, 0.08)
      + Math.min(volatilityRatio * 0.08, 0.07)
      + Math.min(trendRatio * 0.06, 0.05)
      + livePulse * 0.09,
    0.58,
    0.97,
  )

  return {
    sensorId: sensor.id,
    label,
    anomalyScore: Number(anomalyScore.toFixed(3)),
    confidence: Number(confidence.toFixed(3)),
    forecastMw: Number(forecastMw.toFixed(4)),
    currentVoltageV: Number(currentPoint.voltageV.toFixed(1)),
    currentCurrentA: Number(currentPoint.currentA.toFixed(2)),
    reason: buildReason(label, sensor, currentPoint, trendMw, volatilityMw),
    windowStart: history[0].timestamp,
    windowEnd: currentPoint.timestamp,
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
    topIssue: topSensor?.reason ?? `${building.name} is tracking inside the live operating band.`,
    highlights,
  }
}

function normalizeHistory(
  sensor: ModelSensorInput,
  historyOverride: SensorHistoryPoint[] | undefined,
  windowEnd: Date,
): SensorHistoryPoint[] {
  const liveHistory = (historyOverride ?? []).slice(-WINDOW_SIZE)
  if (liveHistory.length >= WINDOW_SIZE) {
    return liveHistory
  }

  const fallbackPoints = buildFallbackHistory(sensor, windowEnd)
  if (!liveHistory.length) {
    return fallbackPoints
  }

  const requiredPrefix = WINDOW_SIZE - liveHistory.length
  const prefix = fallbackPoints.slice(0, requiredPrefix).map((point, index) => ({
    ...point,
    timestamp: new Date(new Date(liveHistory[0].timestamp).getTime() - (requiredPrefix - index) * FALLBACK_STEP_SECONDS * 1000).toISOString(),
  }))
  return [...prefix, ...liveHistory].slice(-WINDOW_SIZE)
}

function buildFallbackHistory(
  sensor: ModelSensorInput,
  windowEnd: Date,
): SensorHistoryPoint[] {
  const checksum = stableNumber(sensor.id)
  const expectedMw = Math.max(sensor.expectedMw, 0.01)
  const currentMw = Math.max(sensor.currentMw || expectedMw, 0.005)
  const history: SensorHistoryPoint[] = []

  for (let index = 0; index < WINDOW_SIZE; index += 1) {
    const timestamp = new Date(windowEnd.getTime() - (WINDOW_SIZE - 1 - index) * FALLBACK_STEP_SECONDS * 1000)
    const progress = (index + 1) / WINDOW_SIZE
    const drift = (currentMw - expectedMw) * progress
    const oscillation = expectedMw * (0.015 * Math.sin((checksum % 7) + progress * Math.PI * 2))
    const powerMw = clamp(expectedMw + drift + oscillation, 0.002, Math.max(expectedMw * 2.6, 0.03))
    const voltageV = clamp(411 - (powerMw / Math.max(expectedMw, 0.01) - 1) * 32 + stableNoise(`${sensor.id}-${index}`, -8, 8), 140, 455)
    history.push({
      timestamp: timestamp.toISOString(),
      voltageV: Number(voltageV.toFixed(1)),
      currentA: Number(computeCurrentA(powerMw, voltageV).toFixed(2)),
      powerMw: Number(powerMw.toFixed(4)),
    })
  }

  return history
}

function inferLabel(
  sensor: ModelSensorInput,
  currentPoint: SensorHistoryPoint,
  ratio: number,
  trendMw: number,
  volatilityMw: number,
): ModelSignalLabel {
  if (sensor.reviewDecision === 'normal') {
    return 'stable'
  }

  if (sensor.comparisonStatus === 'missing_actual' || sensor.comparisonStatus === 'missing_expected') {
    return 'sensor_fault'
  }

  const expectedMw = Math.max(sensor.expectedMw, 0.01)
  const volatilityRatio = volatilityMw / expectedMw

  if (sensor.reviewDecision === 'anomaly') {
    return ratio >= 1 ? 'overload' : 'undervoltage'
  }
  if (ratio <= 0.2 || currentPoint.voltageV <= 130) {
    return 'outage'
  }
  if (volatilityRatio >= 0.34 && ratio > 0.55 && ratio < 1.55) {
    return 'sensor_fault'
  }
  if (ratio >= 1.2 || (trendMw > expectedMw * 0.08 && currentPoint.voltageV < 395)) {
    return 'overload'
  }
  if (ratio <= 0.82 || currentPoint.voltageV < 372) {
    return 'undervoltage'
  }
  if (sensor.comparisonStatus === 'deviation' && ratio < 0.35) {
    return 'outage'
  }
  if (sensor.comparisonStatus === 'deviation' && ratio > 1.12) {
    return 'overload'
  }
  return 'stable'
}

function scoreLabel(
  label: ModelSignalLabel,
  sensor: ModelSensorInput,
  ratio: number,
  trendMw: number,
  volatilityMw: number,
  currentPoint: SensorHistoryPoint,
) {
  const base = {
    stable: 0.14,
    overload: 0.81,
    undervoltage: 0.72,
    sensor_fault: 0.68,
    outage: 0.94,
  }[label]
  const deviationRatio = Math.abs(ratio - 1)
  const expectedMw = Math.max(sensor.expectedMw, 0.01)
  const volatilityRatio = volatilityMw / expectedMw
  const trendRatio = Math.abs(trendMw) / expectedMw
  const voltagePenalty = currentPoint.voltageV < 370 ? 0.06 : 0
  const adjusted = base + Math.min(deviationRatio * 0.18, 0.16) + Math.min(volatilityRatio * 0.18, 0.12) + Math.min(trendRatio * 0.12, 0.08) + voltagePenalty
  return clamp(adjusted, 0.12, 0.99)
}

function buildReason(
  label: ModelSignalLabel,
  sensor: ModelSensorInput,
  currentPoint: SensorHistoryPoint,
  trendMw: number,
  volatilityMw: number,
) {
  const roundedPower = currentPoint.powerMw.toFixed(3)
  const roundedVoltage = currentPoint.voltageV.toFixed(0)
  if (label === 'overload') {
    return `Live demand is climbing toward ${roundedPower} MW and voltage is compressing to ${roundedVoltage} V, so the node is trending into overload risk.`
  }
  if (label === 'undervoltage') {
    return `The node is drawing below its expected band while voltage is sitting near ${roundedVoltage} V, which looks like undervoltage stress.`
  }
  if (label === 'sensor_fault') {
    return `Recent packets are jittering by ${volatilityMw.toFixed(3)} MW across the live window, so the stream looks more like sensor noise than load behaviour.`
  }
  if (label === 'outage') {
    return `Power has collapsed to ${roundedPower} MW in the latest packet, which the model treats as an outage-like event.`
  }
  return sensor.comparisonStatus === 'match'
    ? `Recent packets remain close to the expected band and the short-horizon trend is ${trendMw >= 0 ? 'rising' : 'falling'} gently.`
    : 'Recent live packets are moving, but the model still keeps the node inside its normal operating envelope.'
}

function computeCurrentA(powerMw: number, voltageV: number) {
  return (powerMw * 1_000_000) / (Math.sqrt(3) * Math.max(voltageV, 1) * POWER_FACTOR)
}

function computeVolatility(values: number[]) {
  if (values.length <= 1) return 0
  const mean = average(values)
  const variance = average(values.map((value) => (value - mean) ** 2))
  return Math.sqrt(variance)
}

function average(values: number[]) {
  if (!values.length) return 0
  return values.reduce((total, value) => total + value, 0) / values.length
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
