import { useEffect, useMemo, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import { CircleMarker, MapContainer, Marker, Popup, Polyline, TileLayer, Tooltip, ZoomControl, useMapEvents } from 'react-leaflet'
import { divIcon } from 'leaflet'
import type { LatLngExpression } from 'leaflet'

import './App.css'
import {
  buildPredictiveInsights,
  type BuildingModelInsight,
  type SensorHistoryPoint,
  type SensorModelInsight,
} from './aiModel'
import {
  buildFrontendTelemetryPacket,
  createFrontendStreamRuntime,
  FILE_STREAM_LIMIT,
  FRONTEND_SENSOR_INTERVAL_MS,
  type FrontendStreamRuntime,
} from './sensorSimulation'
import {
  claimDevice,
  compareNitwNetwork,
  dispatchNotification,
  fetchClaimedDevices,
  fetchInventory,
  fetchNitwReference,
  fetchTrainingStreamCollection,
  loginUser,
  registerUser,
  syncNetwork,
  type DeviceRecord,
  type LiveFeedEvent,
  type NotificationSeverity,
  type NitwReference,
  type TrainingStreamTemplate,
} from './serviceX'

type AuthMode = 'login' | 'register'
type VisualStatus = 'unclaimed' | 'good' | 'watch' | 'critical' | 'offline'
type SensorReviewDecision = 'normal' | 'anomaly'
type Session = { token: string; email: string }
type ComparisonRecord = {
  sensor_id: string
  element_type: string
  element_id: string
  measurement: string
  expected: number | null
  actual: number | null
  delta: number | null
  absolute_delta: number | null
  status: string
}
type BuildingSensor = {
  id: string
  name: string
  sensorId: string
  sensorIndex: number
  isActive: boolean
  expectedMw: number
  currentMw: number
  comparedExpectedMw: number | null
  comparedActualMw: number | null
  deltaMw: number | null
  comparisonStatus: string | null
  reviewDecision: SensorReviewDecision | null
  status: VisualStatus
}
type CampusBuilding = {
  id: string
  hardwareId: string
  name: string
  lat: number
  lng: number
  busId: string
  expectedMw: number
  currentMw: number
  sensorCount: number
  claimCount: number
  claimedByCurrentUser: boolean
  status: VisualStatus
  claimPasswordHint: string
  sensors: BuildingSensor[]
}
type DraftBuilding = { name: string; lat: number; lng: number; firstSensorName: string; pMw: string; qMvar: string; vnKv: string }
type DraftSensor = { name: string; pMw: string; qMvar: string }
type NotificationLevel = 'critical' | 'warning' | 'info'
type LiveNotification = {
  id: string
  level: NotificationLevel
  title: string
  detail: string
  timestamp: string
}
type SensorIncidentState = {
  status: VisualStatus
  enteredAtMs: number
  warningSent: boolean
  shutdownTriggered: boolean
}

const SESSION_KEY = 'innothon-session'
const CAMPUS_CENTER: LatLngExpression = [17.98369646253154, 79.53082786635768]
const PUMP_STATION: LatLngExpression = [17.98369646253154, 79.53082786635768]
const LIVE_COMPARE_DEBOUNCE_MS = 250
const SENSOR_HISTORY_LIMIT = 12
const CRITICAL_AUTOSHUTDOWN_MS = 3_000
const PUMP_ICON = divIcon({
  className: 'pump-marker',
  html: '<div class="pump-marker__inner"><strong>Main Feed</strong><span>Campus source</span></div>',
})

function App() {
  const [authMode, setAuthMode] = useState<AuthMode>('login')
  const [session, setSession] = useState<Session | null>(() => {
    const saved = window.localStorage.getItem(SESSION_KEY)
    return saved ? (JSON.parse(saved) as Session) : null
  })
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [authError, setAuthError] = useState('')
  const [authBusy, setAuthBusy] = useState(false)
  const [inventory, setInventory] = useState<DeviceRecord[]>([])
  const [claimedDevices, setClaimedDevices] = useState<DeviceRecord[]>([])
  const [nitwReference, setNitwReference] = useState<NitwReference | null>(null)
  const [trainingStreams, setTrainingStreams] = useState<TrainingStreamTemplate[]>([])
  const [simulatedReadings, setSimulatedReadings] = useState<Record<string, number>>({})
  const [sensorHistory, setSensorHistory] = useState<Record<string, SensorHistoryPoint[]>>({})
  const [simulationUpdatedAt, setSimulationUpdatedAt] = useState('')
  const [compareByElementId, setCompareByElementId] = useState<Record<string, ComparisonRecord>>({})
  const [selectedBuildingId, setSelectedBuildingId] = useState('')
  const [claimPasswords, setClaimPasswords] = useState<Record<string, string>>({})
  const [claimErrorByHardwareId, setClaimErrorByHardwareId] = useState<Record<string, string>>({})
  const [claimBusyHardwareId, setClaimBusyHardwareId] = useState<string | null>(null)
  const [pageError, setPageError] = useState('')
  const [pageBusy, setPageBusy] = useState(false)
  const [superviseBusy, setSuperviseBusy] = useState(false)
  const [supervised, setSupervised] = useState(false)
  const [reviewBySensorId, setReviewBySensorId] = useState<Record<string, SensorReviewDecision>>({})
  const [showBuildingModal, setShowBuildingModal] = useState(false)
  const [addBuildingMode, setAddBuildingMode] = useState(false)
  const [draftBuilding, setDraftBuilding] = useState<DraftBuilding | null>(null)
  const [saveBuildingBusy, setSaveBuildingBusy] = useState(false)
  const [saveBuildingError, setSaveBuildingError] = useState('')
  const [addSensorMode, setAddSensorMode] = useState(false)
  const [draftSensor, setDraftSensor] = useState<DraftSensor | null>(null)
  const [saveSensorBusy, setSaveSensorBusy] = useState(false)
  const [saveSensorError, setSaveSensorError] = useState('')
  const [sensorToggleBusyId, setSensorToggleBusyId] = useState<string | null>(null)
  const [sensorToggleError, setSensorToggleError] = useState('')
  const liveReadingsRef = useRef<Record<string, number>>({})
  const sensorHistoryRef = useRef<Record<string, SensorHistoryPoint[]>>({})
  const simulationTickRef = useRef(0)
  const sensorIncidentRef = useRef<Record<string, SensorIncidentState>>({})
  const streamRuntimeRef = useRef<FrontendStreamRuntime | null>(null)

  useEffect(() => {
    if (session) void loadDashboard(session.token, false)
  }, [session])

  useEffect(() => {
    if (!nitwReference) {
      liveReadingsRef.current = {}
      sensorHistoryRef.current = {}
      simulationTickRef.current = 0
      streamRuntimeRef.current = null
      setSimulatedReadings({})
      setSensorHistory({})
      setSimulationUpdatedAt('')
      return
    }

    streamRuntimeRef.current = createFrontendStreamRuntime(nitwReference, trainingStreams)

    const seededReadings = seedSimulatedReadings(claimedDevices, nitwReference, liveReadingsRef.current)
    const seededAt = new Date().toISOString()
    const seededHistory = seedSensorHistory(nitwReference, seededReadings, sensorHistoryRef.current, seededAt)
    liveReadingsRef.current = seededReadings
    sensorHistoryRef.current = seededHistory
    setSimulatedReadings(seededReadings)
    setSensorHistory(seededHistory)
    setSimulationUpdatedAt(seededAt)
  }, [claimedDevices, nitwReference, trainingStreams])

  useEffect(() => {
    if (!session || !nitwReference) return

    let cancelled = false
    let compareTimeoutId: number | undefined
    let intervalId: number | undefined

    const scheduleCompare = () => {
      if (compareTimeoutId) window.clearTimeout(compareTimeoutId)
      compareTimeoutId = window.setTimeout(async () => {
        try {
          const compare = await compareNitwNetwork(
            session.token,
            filterActiveNetworkPayload(nitwReference),
            liveReadingsRef.current,
          )
          if (cancelled) return
          setCompareByElementId(mapComparisonsByElementId(compare.comparisons ?? []))
          setPageError('')
        } catch (error) {
          if (cancelled) return
          setPageError(error instanceof Error ? `Live simulation paused: ${error.message}` : 'Live simulation paused')
        }
      }, LIVE_COMPARE_DEBOUNCE_MS)
    }

    const emitFrontendPacket = () => {
      simulationTickRef.current += 1
      const packet = buildFrontendTelemetryPacket(
        nitwReference,
        liveReadingsRef.current,
        simulationTickRef.current,
        new Date().toISOString(),
        streamRuntimeRef.current,
      )
      const nextState = applyLiveTelemetryPacket(
        nitwReference,
        packet,
        liveReadingsRef.current,
        sensorHistoryRef.current,
      )
      liveReadingsRef.current = nextState.readings
      sensorHistoryRef.current = nextState.history
      if (!cancelled) {
        setSimulatedReadings(nextState.readings)
        setSensorHistory(nextState.history)
        setSimulationUpdatedAt(nextState.updatedAt)
      }
      if (supervised) scheduleCompare()
    }

    emitFrontendPacket()
    intervalId = window.setInterval(emitFrontendPacket, FRONTEND_SENSOR_INTERVAL_MS)

    return () => {
      cancelled = true
      if (compareTimeoutId) window.clearTimeout(compareTimeoutId)
      if (intervalId) window.clearInterval(intervalId)
    }
  }, [nitwReference, session, supervised])

  const baseBuildings = useMemo<CampusBuilding[]>(() => {
    if (!nitwReference) return []
    const buildingRows = normalizedBuildings(nitwReference)
    const inv = new Map(inventory.filter((d) => !d.nodeKind || d.nodeKind === 'building').map((d) => [d.hardwareId, d]))
    const claimed = new Map(claimedDevices.filter((d) => !d.nodeKind || d.nodeKind === 'building').map((d) => [d.hardwareId, d]))
    const loadsByBuildingId = new Map<string, NitwReference['loads']>()
    for (const load of nitwReference.loads) {
      const buildingId = load.building_id ?? `building_${slugify(load.name || load.id || load.bus_id)}`
      const current = loadsByBuildingId.get(buildingId) ?? []
      current.push(load)
      loadsByBuildingId.set(buildingId, current)
    }
    const linkByElementId = new Map(nitwReference.sensor_links.filter((l) => l.element_type === 'load').map((l) => [l.element_id, l.sensor_id]))
    return buildingRows.map((building) => {
      const hardwareId = building.gateway_hardware_id ?? hardwareIdForBuildingId(building.id)
      const inventoryDevice = inv.get(hardwareId)
      const claimedDevice = claimed.get(hardwareId)
      const readingBySensorId = new Map((claimedDevice?.latestReadings ?? []).map((r) => [r.sensorId, r]))
      const sensors = (loadsByBuildingId.get(building.id) ?? []).map((load) => {
        const sensorId = linkByElementId.get(load.id) ?? `sensor_${load.id}`
        const isActive = load.is_active !== false
        const latest = readingBySensorId.get(sensorId)
        const currentMw = !isActive
          ? 0
          : typeof simulatedReadings[sensorId] === 'number'
            ? simulatedReadings[sensorId]
            : typeof latest?.value === 'number'
              ? latest.value
              : fakeReadingForLoad(load)
        const comparison = isActive && supervised ? compareByElementId[load.id] : undefined
        const reviewDecision = isActive ? reviewBySensorId[load.id] ?? null : null
        let status: VisualStatus = 'offline'
        if (isActive) {
          status = claimedDevice ? 'good' : 'unclaimed'
          if (claimedDevice && supervised) status = comparisonVisualStatus(comparison?.status ?? null)
          if (reviewDecision === 'normal') status = 'good'
        }
        return {
          id: load.id,
          name: load.name,
          sensorId,
          sensorIndex: load.sensor_index ?? extractSensorIndex(load.id),
          isActive,
          expectedMw: isActive ? load.p_mw ?? 0 : 0,
          currentMw,
          comparedExpectedMw: comparison?.expected ?? null,
          comparedActualMw: comparison?.actual ?? null,
          deltaMw: comparison?.delta ?? null,
          comparisonStatus: isActive ? comparison?.status ?? null : 'inactive',
          reviewDecision,
          status,
        }
      }).sort((a, b) => a.sensorIndex - b.sensorIndex || a.name.localeCompare(b.name))
      const hasActiveSensors = sensors.some((sensor) => sensor.isActive)
      let buildingStatus: VisualStatus = claimedDevice ? 'good' : 'unclaimed'
      if (claimedDevice && !hasActiveSensors) {
        buildingStatus = 'offline'
      } else if (claimedDevice && supervised) {
        buildingStatus = summarizeSensorStatuses(sensors)
      }
      return {
        id: building.id,
        hardwareId,
        name: building.name,
        lat: building.lat,
        lng: building.long,
        busId: building.bus_id,
        expectedMw: sum(sensors.map((s) => s.expectedMw)),
        currentMw: sum(sensors.map((s) => s.currentMw)),
        sensorCount: sensors.length || building.sensor_count || 0,
        claimCount: inventoryDevice?.claimCount ?? 0,
        claimedByCurrentUser: Boolean(claimedDevice),
        status: buildingStatus,
        claimPasswordHint: `claim-${building.id}`,
        sensors,
      }
    }).sort((a, b) => a.name.localeCompare(b.name))
  }, [claimedDevices, compareByElementId, inventory, nitwReference, reviewBySensorId, simulatedReadings, supervised])

  const modelInsights = useMemo(() => buildPredictiveInsights(
    baseBuildings.map((building) => ({
      id: building.id,
      name: building.name,
      expectedMw: building.expectedMw,
      currentMw: building.currentMw,
      sensors: building.sensors.filter((sensor) => sensor.isActive).map((sensor) => ({
        id: sensor.sensorId,
        name: sensor.name,
        expectedMw: sensor.expectedMw,
        currentMw: sensor.currentMw,
        sensorIndex: sensor.sensorIndex,
        comparisonStatus: sensor.comparisonStatus,
        reviewDecision: sensor.reviewDecision,
        status: sensor.status,
      })),
    })),
    sensorHistory,
  ), [baseBuildings, sensorHistory])
  const buildings = useMemo<CampusBuilding[]>(() => baseBuildings.map((building) => {
    const nextSensors = building.sensors.map((sensor) => ({
      ...sensor,
      status: resolveSensorVisualStatus(sensor, modelInsights.sensors[sensor.sensorId]),
    }))
    return {
      ...building,
      sensors: nextSensors,
      status: resolveBuildingVisualStatus(building.status, nextSensors, modelInsights.buildings[building.id]),
    }
  }), [baseBuildings, modelInsights])
  const selectedBuilding = buildings.find((b) => b.id === selectedBuildingId) ?? buildings[0] ?? null
  const selectedBuildingHasActiveSensors = Boolean(selectedBuilding?.sensors.some((sensor) => sensor.isActive))
  const selectedBuildingActiveSensorCount = selectedBuilding?.sensors.filter((sensor) => sensor.isActive).length ?? 0
  const selectedBuildingModel = selectedBuilding ? modelInsights.buildings[selectedBuilding.id] : null
  const stats = useMemo(() => ({
    claimed: buildings.filter((b) => b.claimedByCurrentUser).length,
    blue: buildings.filter((b) => b.status === 'unclaimed').length,
    green: buildings.filter((b) => b.status === 'good').length,
    orange: buildings.filter((b) => b.status === 'watch').length,
    red: buildings.filter((b) => b.status === 'critical').length,
    sensors: buildings.reduce((total, b) => total + b.sensorCount, 0),
    activeSensors: buildings.reduce((total, b) => total + b.sensors.filter((sensor) => sensor.isActive).length, 0),
  }), [buildings])
  const liveNotifications = useMemo<LiveNotification[]>(() => {
    const alerts = buildings.flatMap((building) => building.sensors.flatMap((sensor) => {
      const sensorModel = modelInsights.sensors[sensor.sensorId]
      const lastPacket = sensorHistory[sensor.sensorId]?.[sensorHistory[sensor.sensorId].length - 1]
      const shouldNotify = sensor.status === 'critical' || sensor.status === 'watch' || (sensorModel && sensorModel.label !== 'stable' && sensorModel.anomalyScore >= 0.55)
      if (!shouldNotify || !sensorModel) return []
      const level: NotificationLevel =
        sensor.status === 'critical' || sensorModel.label === 'outage' || sensorModel.label === 'overload'
          ? 'critical'
          : 'warning'
      return [{
        id: `${building.id}-${sensor.id}-${sensorModel.label}`,
        level,
        title: `${building.name} / ${sensor.name}`,
        detail: buildNotificationDetail(sensor, sensorModel),
        timestamp: lastPacket?.timestamp ?? simulationUpdatedAt,
      }]
    }))

    if (alerts.length) {
      return alerts
        .sort((left, right) => right.timestamp.localeCompare(left.timestamp))
        .slice(0, 6)
    }

    return simulationUpdatedAt
      ? [{
        id: 'live-stream-ok',
        level: 'info',
        title: stats.activeSensors ? 'All sensor nodes simulating' : 'All sensors are turned off',
        detail: stats.activeSensors
          ? `${stats.activeSensors} active nodes are being simulated locally with no AI issues above the watch threshold.`
          : 'No active sensors are currently running in the local simulator.',
        timestamp: simulationUpdatedAt,
      }]
      : []
  }, [buildings, modelInsights, sensorHistory, simulationUpdatedAt, stats.activeSensors])

  useEffect(() => {
    if (!session) {
      sensorIncidentRef.current = {}
      return
    }

    const now = Date.now()
    const activeIncidentKeys = new Set<string>()

    for (const building of buildings) {
      if (!building.claimedByCurrentUser) continue

      for (const sensor of building.sensors) {
        activeIncidentKeys.add(sensor.id)

        if (!sensor.isActive || sensor.status === 'good' || sensor.status === 'unclaimed' || sensor.status === 'offline') {
          delete sensorIncidentRef.current[sensor.id]
          continue
        }

        const sensorModel = modelInsights.sensors[sensor.sensorId]
        const currentIncident = sensorIncidentRef.current[sensor.id]

        if (!currentIncident || currentIncident.status !== sensor.status) {
          sensorIncidentRef.current[sensor.id] = {
            status: sensor.status,
            enteredAtMs: now,
            warningSent: sensor.status === 'watch',
            shutdownTriggered: false,
          }

          if (sensor.status === 'watch') {
            void dispatchSensorIncidentNotification({
              severity: 'medium',
              title: `${building.name} / ${sensor.name} warning`,
              message: `${sensor.name} moved into orange status. The AI is warning about ${sensorModel ? modelLabel(sensorModel.label).replace('AI ', '').toLowerCase() : 'node instability'}, and the user can turn the node off if needed.`,
              buildingName: building.name,
              sensorName: sensor.name,
              metadata: {
                nodeStatus: sensor.status,
                aiLabel: sensorModel?.label ?? 'stable',
                anomalyScore: sensorModel?.anomalyScore ?? null,
                suggestedAction: 'manual_turn_off_available',
                sensorId: sensor.sensorId,
              },
            })
          }
          continue
        }

        if (sensor.status === 'critical' && !currentIncident.shutdownTriggered && now - currentIncident.enteredAtMs >= CRITICAL_AUTOSHUTDOWN_MS) {
          currentIncident.shutdownTriggered = true
          void autoShutdownSensor(building, sensor, sensorModel, Math.round((now - currentIncident.enteredAtMs) / 1000))
        }
      }
    }

    for (const sensorId of Object.keys(sensorIncidentRef.current)) {
      if (!activeIncidentKeys.has(sensorId)) {
        delete sensorIncidentRef.current[sensorId]
      }
    }
  }, [buildings, modelInsights, nitwReference, selectedBuildingId, session, showBuildingModal])

  async function loadDashboard(token: string, runSupervision: boolean) {
    setPageBusy(true)
    setPageError('')
    try {
      const [inventoryData, claimedData, nitwData, streamCollection] = await Promise.all([
        fetchInventory(token),
        fetchClaimedDevices(token),
        fetchNitwReference(token),
        fetchTrainingStreamCollection(token, FILE_STREAM_LIMIT),
      ])
      const seededAt = simulationUpdatedAt || new Date().toISOString()
      const nextSeededReadings = seedSimulatedReadings(claimedData, nitwData, liveReadingsRef.current)
      const nextSensorHistory = seedSensorHistory(nitwData, nextSeededReadings, sensorHistoryRef.current, seededAt)
      liveReadingsRef.current = nextSeededReadings
      sensorHistoryRef.current = nextSensorHistory
      setInventory(inventoryData)
      setClaimedDevices(claimedData)
      setNitwReference(nitwData)
      setTrainingStreams(streamCollection.streams ?? [])
      setSimulatedReadings(nextSeededReadings)
      setSensorHistory(nextSensorHistory)
      setSimulationUpdatedAt(seededAt)
      setSelectedBuildingId((current) => current || normalizedBuildings(nitwData)[0]?.id || '')
      if (!runSupervision) {
        setCompareByElementId({})
        setSupervised(false)
        return
      }
      setCompareByElementId(await superviseBuildings(token, claimedData, nitwData, nextSeededReadings))
      setSupervised(true)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Failed to load dashboard')
    } finally {
      setPageBusy(false)
    }
  }

  async function handleAuthSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault()
    setAuthBusy(true)
    setAuthError('')
    try {
      const result = authMode === 'register' ? await registerUser(email.trim(), password) : await loginUser(email.trim(), password)
      const nextSession = { token: result.access_token, email: result.user.email }
      window.localStorage.setItem(SESSION_KEY, JSON.stringify(nextSession))
      setSession(nextSession)
      setEmail('')
      setPassword('')
    } catch (error) {
      setAuthError(error instanceof Error ? error.message : 'Authentication failed')
    } finally {
      setAuthBusy(false)
    }
  }

  async function handleClaim(hardwareId: string) {
    if (!session) return
    const claimPassword = claimPasswords[hardwareId]?.trim()
    if (!claimPassword) {
      setClaimErrorByHardwareId((current) => ({ ...current, [hardwareId]: 'Enter the building password to claim it.' }))
      return
    }
    setClaimBusyHardwareId(hardwareId)
    setClaimErrorByHardwareId((current) => ({ ...current, [hardwareId]: '' }))
    try {
      await claimDevice(session.token, hardwareId, claimPassword)
      await loadDashboard(session.token, supervised)
    } catch (error) {
      setClaimErrorByHardwareId((current) => ({ ...current, [hardwareId]: error instanceof Error ? error.message : 'Claim failed' }))
    } finally {
      setClaimBusyHardwareId(null)
    }
  }

  async function handleSupervise() {
    if (!session) return
    setSuperviseBusy(true)
    setPageError('')
    try {
      const claimedData = claimedDevices.length ? claimedDevices : await fetchClaimedDevices(session.token)
      const nitwData = nitwReference ?? await fetchNitwReference(session.token)
      const seededAt = simulationUpdatedAt || new Date().toISOString()
      const nextSeededReadings = seedSimulatedReadings(claimedData, nitwData, liveReadingsRef.current)
      const nextSensorHistory = seedSensorHistory(nitwData, nextSeededReadings, sensorHistoryRef.current, seededAt)
      liveReadingsRef.current = nextSeededReadings
      sensorHistoryRef.current = nextSensorHistory
      setClaimedDevices(claimedData)
      setNitwReference(nitwData)
      setSimulatedReadings(nextSeededReadings)
      setSensorHistory(nextSensorHistory)
      setSimulationUpdatedAt(seededAt)
      setCompareByElementId(await superviseBuildings(session.token, claimedData, nitwData, nextSeededReadings))
      setSupervised(true)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Simulation failed')
    } finally {
      setSuperviseBusy(false)
    }
  }

  function beginAddBuildingMode() {
    setAddBuildingMode(true)
    setSaveBuildingError('')
    setDraftBuilding((current) => current ?? createInitialDraftBuilding())
  }

  function cancelAddBuilding() {
    setAddBuildingMode(false)
    setDraftBuilding(null)
    setSaveBuildingError('')
  }

  async function handleSaveBuilding() {
    if (!session || !nitwReference || !draftBuilding) return
    setSaveBuildingBusy(true)
    setSaveBuildingError('')
    try {
      const { buildingId, networkPayload } = buildNetworkWithDraftBuilding(nitwReference, draftBuilding)
      setSelectedBuildingId(buildingId)
      await syncNetwork(session.token, networkPayload)
      await loadDashboard(session.token, supervised)
      setSelectedBuildingId(buildingId)
      setShowBuildingModal(true)
      setAddBuildingMode(false)
      setDraftBuilding(null)
    } catch (error) {
      setSaveBuildingError(error instanceof Error ? error.message : 'Failed to add building')
    } finally {
      setSaveBuildingBusy(false)
    }
  }

  function beginAddSensorMode() {
    if (!selectedBuilding) return
    setAddSensorMode(true)
    setSaveSensorError('')
    setDraftSensor({
      name: `${selectedBuilding.name} Sensor ${String(selectedBuilding.sensorCount + 1).padStart(2, '0')}`,
      pMw: '0.05',
      qMvar: '0.02',
    })
  }

  function cancelAddSensor() {
    setAddSensorMode(false)
    setDraftSensor(null)
    setSaveSensorError('')
  }

  async function handleSaveSensor() {
    if (!session || !nitwReference || !selectedBuilding || !draftSensor) return
    setSaveSensorBusy(true)
    setSaveSensorError('')
    try {
      await syncNetwork(session.token, buildNetworkWithAddedSensor(nitwReference, selectedBuilding, draftSensor))
      await loadDashboard(session.token, supervised)
      setSelectedBuildingId(selectedBuilding.id)
      setShowBuildingModal(true)
      setAddSensorMode(false)
      setDraftSensor(null)
    } catch (error) {
      setSaveSensorError(error instanceof Error ? error.message : 'Failed to add node')
    } finally {
      setSaveSensorBusy(false)
    }
  }

  async function handleSetSensorActive(sensorId: string, nextIsActive: boolean) {
    if (!selectedBuilding) return
    try {
      await updateSensorActivity(sensorId, nextIsActive, {
        restoreBuildingId: selectedBuilding.id,
        reopenModal: showBuildingModal,
        failureLabel: `Failed to turn ${nextIsActive ? 'on' : 'off'} sensor`,
      })
    } catch {
      // The shared helper already surfaces the error in UI state.
    }
  }

  async function updateSensorActivity(
    sensorId: string,
    nextIsActive: boolean,
    options?: { restoreBuildingId?: string; reopenModal?: boolean; failureLabel?: string },
  ) {
    if (!session || !nitwReference) return
    setSensorToggleBusyId(sensorId)
    setSensorToggleError('')
    try {
      await syncNetwork(session.token, buildNetworkWithSensorActivity(nitwReference, sensorId, nextIsActive))
      await loadDashboard(session.token, supervised)
      if (options?.restoreBuildingId) setSelectedBuildingId(options.restoreBuildingId)
      if (options?.reopenModal) setShowBuildingModal(true)
    } catch (error) {
      setSensorToggleError(error instanceof Error ? error.message : options?.failureLabel ?? `Failed to turn ${nextIsActive ? 'on' : 'off'} sensor`)
      throw error
    } finally {
      setSensorToggleBusyId(null)
    }
  }

  function openBuildingModal(buildingId: string) {
    setSelectedBuildingId(buildingId)
    setShowBuildingModal(true)
    setAddSensorMode(false)
    setSaveSensorError('')
    setSensorToggleError('')
  }

  function closeBuildingModal() {
    setShowBuildingModal(false)
    setAddSensorMode(false)
    setSaveSensorError('')
    setSensorToggleError('')
  }

  function markSensorReview(sensorId: string, decision: SensorReviewDecision) {
    setReviewBySensorId((current) => ({ ...current, [sensorId]: decision }))
  }

  function clearSensorReview(sensorId: string) {
    setReviewBySensorId((current) => {
      const next = { ...current }
      delete next[sensorId]
      return next
    })
  }

  function logout() {
    window.localStorage.removeItem(SESSION_KEY)
    setSession(null)
    setInventory([])
    setClaimedDevices([])
    setNitwReference(null)
    setTrainingStreams([])
    setSimulatedReadings({})
    setSensorHistory({})
    setSimulationUpdatedAt('')
    setCompareByElementId({})
    setSelectedBuildingId('')
    setSupervised(false)
    setReviewBySensorId({})
    setSensorToggleBusyId(null)
    setSensorToggleError('')
    setShowBuildingModal(false)
    setAddBuildingMode(false)
    setDraftBuilding(null)
    liveReadingsRef.current = {}
    sensorHistoryRef.current = {}
    simulationTickRef.current = 0
    sensorIncidentRef.current = {}
    streamRuntimeRef.current = null
  }

  function renderClaimBox(building: CampusBuilding) {
    if (building.claimedByCurrentUser) {
      return (
        <div className="claim-success">
          {supervised
            ? 'Claimed by you. File-backed sensor packets are running and the supervision simulation is active.'
            : 'Claimed by you. File-backed sensor packets are running. Run the simulation when you want to supervise the node health.'}
        </div>
      )
    }
    return (
      <div className="claim-box">
        <label>
          <span>Building claim password</span>
          <input
            onChange={(event) => setClaimPasswords((current) => ({ ...current, [building.hardwareId]: event.target.value }))}
            placeholder={building.claimPasswordHint}
            type="password"
            value={claimPasswords[building.hardwareId] ?? ''}
          />
        </label>
        {claimErrorByHardwareId[building.hardwareId] ? <div className="form-error">{claimErrorByHardwareId[building.hardwareId]}</div> : null}
        <button disabled={claimBusyHardwareId === building.hardwareId} onClick={() => void handleClaim(building.hardwareId)} type="button">
          {claimBusyHardwareId === building.hardwareId ? 'Claiming...' : 'Claim building'}
        </button>
      </div>
    )
  }

  async function dispatchSensorIncidentNotification({
    severity,
    title,
    message,
    buildingName,
    sensorName,
    metadata,
  }: {
    severity: NotificationSeverity
    title: string
    message: string
    buildingName: string
    sensorName: string
    metadata: Record<string, unknown>
  }) {
    if (!session) return
    try {
      await dispatchNotification(session.token, {
        title,
        message,
        severity,
        buildingName,
        sensorName,
        networkName: nitwReference?.network.name ?? 'NITW',
        metadata,
      })
    } catch (error) {
      console.warn('Notification dispatch failed', error)
    }
  }

  async function autoShutdownSensor(
    building: CampusBuilding,
    sensor: BuildingSensor,
    sensorModel: SensorModelInsight | undefined,
    persistedSeconds: number,
  ) {
    try {
      await updateSensorActivity(sensor.id, false, {
        restoreBuildingId: selectedBuildingId || building.id,
        reopenModal: showBuildingModal && selectedBuildingId === building.id,
        failureLabel: 'Automatic shutdown failed',
      })
      await dispatchSensorIncidentNotification({
        severity: 'critical',
        title: `${building.name} / ${sensor.name} auto shutdown`,
        message: `${sensor.name} stayed in red status for ${persistedSeconds}s, so the system turned it off automatically and notified the user.`,
        buildingName: building.name,
        sensorName: sensor.name,
        metadata: {
          nodeStatus: sensor.status,
          aiLabel: sensorModel?.label ?? 'stable',
          anomalyScore: sensorModel?.anomalyScore ?? null,
          actionTaken: 'turned_off_automatically',
          persistedSeconds,
          sensorId: sensor.sensorId,
        },
      })
    } catch (error) {
      await dispatchSensorIncidentNotification({
        severity: 'critical',
        title: `${building.name} / ${sensor.name} auto shutdown failed`,
        message: `${sensor.name} stayed in red status for ${persistedSeconds}s, but automatic turn off failed. User action is required immediately.`,
        buildingName: building.name,
        sensorName: sensor.name,
        metadata: {
          nodeStatus: sensor.status,
          aiLabel: sensorModel?.label ?? 'stable',
          anomalyScore: sensorModel?.anomalyScore ?? null,
          actionTaken: 'auto_shutdown_failed',
          persistedSeconds,
          sensorId: sensor.sensorId,
          error: error instanceof Error ? error.message : 'unknown_error',
        },
      })
    }
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="kicker">INNOTHON Access</p>
          <h1>{authMode === 'login' ? 'Login to claim campus buildings' : 'Create your operator account'}</h1>
          <p className="auth-copy">Staff users can sign in, claim buildings, and inspect internal sensor anomalies building by building.</p>
          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <label><span>Email</span><input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required /></label>
            <label><span>Password</span><input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={8} required /></label>
            {authError ? <div className="form-error">{authError}</div> : null}
            <button disabled={authBusy} type="submit">{authBusy ? 'Please wait...' : authMode === 'login' ? 'Login' : 'Register'}</button>
          </form>
          <button className="ghost-button" onClick={() => setAuthMode(authMode === 'login' ? 'register' : 'login')} type="button">
            {authMode === 'login' ? 'Need an account? Register' : 'Already have an account? Login'}
          </button>
        </section>
      </main>
    )
  }

  return (
    <main className="network-shell">
      <header className="network-header">
        <div>
          <p className="kicker">NITW Building Control</p>
          <h1>Claim buildings and watch live sensor node health</h1>
          <p className="header-copy">Signed in as {session.email}. Blue means unclaimed, and claimed nodes switch live between green, orange, and red from 5 file-backed streams plus AI.</p>
        </div>
        <div className="header-actions">
          <div className="header-stats">
            <div className="header-stat"><span>Claimed buildings</span><strong>{stats.claimed}</strong></div>
            <div className="header-stat header-stat--unclaimed"><span>Blue buildings</span><strong>{stats.blue}</strong></div>
            <div className="header-stat header-stat--good"><span>Green buildings</span><strong>{stats.green}</strong></div>
            <div className="header-stat header-stat--watch"><span>Orange buildings</span><strong>{stats.orange}</strong></div>
            <div className="header-stat header-stat--critical"><span>Red buildings</span><strong>{stats.red}</strong></div>
            <div className="header-stat"><span>Live nodes</span><strong>{stats.activeSensors}</strong></div>
          </div>
          <div className="header-button-row">
            <button className="ghost-button" disabled={pageBusy || saveBuildingBusy} onClick={beginAddBuildingMode} type="button">Add building</button>
            <button className="ghost-button ghost-button--accent" disabled={pageBusy || superviseBusy} onClick={() => void handleSupervise()} type="button">
              {superviseBusy ? 'Simulating...' : 'Simulate Supervision'}
            </button>
            <button className="ghost-button" onClick={logout} type="button">Logout</button>
          </div>
        </div>
      </header>

      {pageError ? <section className="banner banner--error">{pageError}</section> : null}

      <section className="network-layout">
        <section className="map-card">
          <MapContainer center={CAMPUS_CENTER} className="network-map" zoom={16} zoomControl={false}>
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <ZoomControl position="bottomright" />
            <MapPlacementHandler active={addBuildingMode} onPlace={(lat, lng) => setDraftBuilding((current) => current ? { ...current, lat, lng } : { ...createInitialDraftBuilding(), lat, lng })} />

            {buildings.map((building) => (
              <Polyline key={`line-${building.hardwareId}`} pathOptions={{ color: edgeColor(building.status), dashArray: '10 10', weight: 4 }} positions={[PUMP_STATION, [building.lat, building.lng]]} />
            ))}

            <Marker icon={PUMP_ICON} position={PUMP_STATION}><Popup><div className="popup-card"><strong>Main Feed</strong><span>Campus distribution source.</span></div></Popup></Marker>

            {draftBuilding ? (
              <Marker
                draggable
                eventHandlers={{ dragend: (event) => { const position = event.target.getLatLng(); setDraftBuilding((current) => current ? { ...current, lat: position.lat, lng: position.lng } : current) } }}
                position={[draftBuilding.lat, draftBuilding.lng]}
              >
                <Popup><div className="popup-card"><strong>{draftBuilding.name || 'New building'}</strong><span>Drag to place the new building.</span><span>{draftBuilding.lat.toFixed(6)}, {draftBuilding.lng.toFixed(6)}</span></div></Popup>
              </Marker>
            ) : null}

            {buildings.map((building) => (
              <CircleMarker
                center={[building.lat, building.lng]}
                eventHandlers={{ click: () => setSelectedBuildingId(building.id) }}
                key={building.hardwareId}
                pathOptions={{ color: borderColor(building.status), fillColor: fillColor(building.status), fillOpacity: 0.94, weight: selectedBuildingId === building.id ? 4 : 2 }}
                radius={selectedBuildingId === building.id ? 13 : 11}
              >
                <Tooltip direction="top" offset={[0, -8]}>{building.name}</Tooltip>
                <Popup>
                  <div className="popup-card popup-card--wide">
                    <strong>{building.name}</strong>
                    <span>{building.hardwareId}</span>
                    <span>Bus: {building.busId}</span>
                    <span>Sensors inside: {building.sensorCount}</span>
                    <span>Expected aggregate: {building.expectedMw.toFixed(2)} MW</span>
                    <span>Current aggregate: {building.currentMw.toFixed(2)} MW</span>
                    <span>Orange sensors: {countSensorsByStatus(building.sensors, 'watch')}</span>
                    <span>Red sensors: {countSensorsByStatus(building.sensors, 'critical')}</span>
                    <span>AI high-risk sensors: {modelInsights.buildings[building.id]?.highRiskSensorCount ?? 0}</span>
                    <span className={`map-badge map-badge--${building.status}`}>{statusColorLabel(building.status)} / {statusLabel(building.status)}</span>
                    <button className="ghost-button ghost-button--accent" onClick={() => openBuildingModal(building.id)} type="button">Expand building</button>
                    {renderClaimBox(building)}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </section>
        <aside className="side-panel">
          {addBuildingMode ? (
            <article className="panel panel--composer">
              <div className="panel-heading">
                <div><p className="kicker">Building Composer</p><h2>Add a building</h2></div>
                <span className="status-badge status-unclaimed">Draft</span>
              </div>
              <p className="composer-copy">Click on the map to place the building, drag the draft marker if needed, then save the building with its first node.</p>
              <div className="composer-form">
                <label><span>Building name</span><input onChange={(event) => setDraftBuilding((current) => current ? { ...current, name: event.target.value } : current)} placeholder="New academic block" value={draftBuilding?.name ?? ''} /></label>
                <label><span>First node name</span><input onChange={(event) => setDraftBuilding((current) => current ? { ...current, firstSensorName: event.target.value } : current)} placeholder="Main panel sensor" value={draftBuilding?.firstSensorName ?? ''} /></label>
                <label><span>Active load (MW)</span><input min="0" onChange={(event) => setDraftBuilding((current) => current ? { ...current, pMw: event.target.value } : current)} step="0.01" type="number" value={draftBuilding?.pMw ?? ''} /></label>
                <label><span>Reactive load (MVAR)</span><input min="0" onChange={(event) => setDraftBuilding((current) => current ? { ...current, qMvar: event.target.value } : current)} step="0.01" type="number" value={draftBuilding?.qMvar ?? ''} /></label>
                <label><span>Bus voltage (kV)</span><input min="0" onChange={(event) => setDraftBuilding((current) => current ? { ...current, vnKv: event.target.value } : current)} step="0.1" type="number" value={draftBuilding?.vnKv ?? ''} /></label>
              </div>
              {draftBuilding ? <div className="draft-coordinates">Draft position: {draftBuilding.lat.toFixed(6)}, {draftBuilding.lng.toFixed(6)}</div> : null}
              {saveBuildingError ? <div className="form-error">{saveBuildingError}</div> : null}
              <div className="composer-actions">
                <button disabled={saveBuildingBusy || !draftBuilding?.name.trim() || !draftBuilding?.firstSensorName.trim()} onClick={() => void handleSaveBuilding()} type="button">
                  {saveBuildingBusy ? 'Saving building...' : 'Save building'}
                </button>
                <button className="ghost-button" onClick={cancelAddBuilding} type="button">Cancel</button>
              </div>
            </article>
          ) : null}

          <article className="panel panel--summary">
            <div className="metric"><span>Total buildings</span><strong>{buildings.length}</strong></div>
            <div className="metric"><span>Total internal sensors</span><strong>{stats.sensors}</strong></div>
            <div className="metric"><span>Stream mode</span><strong>{pageBusy ? 'Refreshing packets...' : supervised ? 'CSV packets + simulation' : 'CSV packets only'}</strong></div>
            <div className="metric"><span>Data collection</span><strong>{trainingStreams.length ? `${trainingStreams.length} file streams` : 'Synthetic fallback'}</strong></div>
            <div className="metric"><span>AI window</span><strong>{formatLiveWindow(modelInsights.summary.windowSize, modelInsights.summary.windowStart, modelInsights.summary.windowEnd)}</strong></div>
            <div className="metric"><span>AI source</span><strong>{liveSourceLabel(modelInsights.summary.source)}</strong></div>
            <div className="metric"><span>Last sensor tick</span><strong>{simulationUpdatedAt ? formatClock(simulationUpdatedAt) : '--'}</strong></div>
          </article>

          <article className="panel panel--legend">
            <div className="panel-heading"><div><p className="kicker">Node Legend</p><h2>Live color logic</h2></div></div>
            <div className="legend-grid">
              {(['unclaimed', 'good', 'watch', 'critical'] as const).map((status) => (
                <div className={`legend-pill legend-pill--${status}`} key={status}>
                  <span className={`legend-dot legend-dot--${status}`} />
                  <strong>{statusColorLabel(status)}</strong>
                  <span>{statusLabel(status)}</span>
                </div>
              ))}
            </div>
            <p className="legend-copy">Node colors update in real time from the AI prediction window fed by the file stream collection. Use Simulate Supervision when you want to replay the operator supervision view.</p>
          </article>

          <article className="panel panel--alerts">
            <div className="panel-heading"><div><p className="kicker">Notifications</p><h2>Live anomaly feed</h2></div></div>
            <div className="notification-list">
              {liveNotifications.map((notification) => (
                <article className={`notification-card notification-card--${notification.level}`} key={notification.id}>
                  <div className="notification-card__header">
                    <strong>{notification.title}</strong>
                    <span>{formatClock(notification.timestamp)}</span>
                  </div>
                  <p>{notification.detail}</p>
                </article>
              ))}
            </div>
          </article>

          <article className="panel panel--list">
            <div className="panel-heading"><div><p className="kicker">Buildings</p><h2>Claim and inspect</h2></div></div>
            <div className="building-list">
              {buildings.map((building) => (
                <button className="building-row" key={building.id} onClick={() => setSelectedBuildingId(building.id)} type="button">
                  <div><strong>{building.name}</strong><span>{building.sensors.filter((sensor) => sensor.isActive).length}/{building.sensorCount} active sensors | {building.expectedMw.toFixed(2)} MW expected</span></div>
                  <span className={`mini-badge status-${building.status}`}>{statusLabel(building.status)}</span>
                </button>
              ))}
            </div>
          </article>

          {selectedBuilding ? (
            <article className="panel">
              <div className="panel-heading">
                <div><p className="kicker">Selected Building</p><h2>{selectedBuilding.name}</h2></div>
                <span className={`status-badge status-${selectedBuilding.status}`}>{statusLabel(selectedBuilding.status)}</span>
              </div>
              <div className="detail-list">
                <div><span>Hardware ID</span><strong>{selectedBuilding.hardwareId}</strong></div>
                <div><span>Bus</span><strong>{selectedBuilding.busId}</strong></div>
                <div><span>Sensors active</span><strong>{selectedBuildingActiveSensorCount} / {selectedBuilding.sensorCount}</strong></div>
                <div><span>Expected aggregate</span><strong>{selectedBuilding.expectedMw.toFixed(2)} MW</strong></div>
                <div><span>Current aggregate</span><strong>{selectedBuilding.currentMw.toFixed(2)} MW</strong></div>
                <div><span>AI top label</span><strong>{selectedBuildingHasActiveSensors && selectedBuildingModel ? modelLabel(selectedBuildingModel.label) : selectedBuildingHasActiveSensors ? 'Waiting' : 'Turned Off'}</strong></div>
                <div><span>AI risk score</span><strong>{selectedBuildingHasActiveSensors && selectedBuildingModel ? formatPercent(selectedBuildingModel.anomalyScore) : '--'}</strong></div>
                <div><span>Forecast next 30m</span><strong>{selectedBuildingHasActiveSensors && selectedBuildingModel ? `${selectedBuildingModel.forecastMw.toFixed(2)} MW` : '--'}</strong></div>
              </div>
              <div className="node-preview-list">
                {selectedBuilding.sensors.slice(0, 5).map((sensor) => {
                  const sensorModel = modelInsights.sensors[sensor.sensorId]
                  const latestPoint = sensorHistory[sensor.sensorId]?.[sensorHistory[sensor.sensorId].length - 1]
                  return (
                    <article className={`node-preview node-preview--${sensor.status}`} key={sensor.id}>
                      <div className="node-preview__header">
                        <div>
                          <strong>{sensor.name}</strong>
                          <span>{sensor.sensorId}</span>
                        </div>
                        <div className="node-preview__badges">
                          <span className={`mini-badge status-${sensor.status}`}>{statusLabel(sensor.status)}</span>
                          <span className={sensor.isActive ? `mini-badge model-badge model-badge--${sensorModel ? modelToneClass(sensorModel.label) : 'stable'}` : 'mini-badge status-offline'}>
                            {sensor.isActive ? sensorModel ? modelLabel(sensorModel.label) : 'Streaming' : 'Turned Off'}
                          </span>
                        </div>
                      </div>
                      <div className="node-preview__metrics">
                        <span>{sensor.currentMw.toFixed(3)} MW</span>
                        <span>{sensor.isActive && latestPoint ? `${latestPoint.voltageV.toFixed(0)} V` : '--'}</span>
                        <span>{sensor.isActive && latestPoint ? formatRelativeTick(latestPoint.timestamp) : 'Sensor off'}</span>
                      </div>
                      <div className="telemetry-chip-row">
                        {buildTelemetryChips(latestPoint, sensor.isActive).map((chip) => (
                          <span className={`telemetry-chip telemetry-chip--${chip.tone}`} key={chip.label}>{chip.label}</span>
                        ))}
                      </div>
                    </article>
                  )
                })}
              </div>
              <div className="panel-action-row"><button className="ghost-button ghost-button--accent" onClick={() => openBuildingModal(selectedBuilding.id)} type="button">Open building view</button></div>
              {renderClaimBox(selectedBuilding)}
            </article>
          ) : null}
        </aside>
      </section>

      {showBuildingModal && selectedBuilding ? (
        <div className="modal-backdrop" onClick={closeBuildingModal} role="presentation">
          <section className="building-modal" onClick={(event) => event.stopPropagation()} role="dialog" aria-modal="true">
            <div className="building-modal__header">
              <div>
                <p className="kicker">Building View</p>
                <h2>{selectedBuilding.name}</h2>
                <p className="header-copy">{selectedBuildingActiveSensorCount} active of {selectedBuilding.sensorCount} internal sensors on {selectedBuilding.busId}</p>
              </div>
              <div className="building-modal__actions">
                <span className={`status-badge status-${selectedBuilding.status}`}>{statusLabel(selectedBuilding.status)}</span>
                <button className="ghost-button" onClick={closeBuildingModal} type="button">Close</button>
              </div>
            </div>

            <div className="building-modal__summary">
              <div className="metric"><span>Expected aggregate</span><strong>{selectedBuilding.expectedMw.toFixed(2)} MW</strong></div>
              <div className="metric"><span>Current aggregate</span><strong>{selectedBuilding.currentMw.toFixed(2)} MW</strong></div>
              <div className="metric"><span>Orange sensors</span><strong>{countSensorsByStatus(selectedBuilding.sensors, 'watch')}</strong></div>
              <div className="metric"><span>Red sensors</span><strong>{countSensorsByStatus(selectedBuilding.sensors, 'critical')}</strong></div>
              <div className="metric"><span>Active sensors</span><strong>{selectedBuildingActiveSensorCount}</strong></div>
              <div className="metric"><span>AI high-risk sensors</span><strong>{selectedBuildingHasActiveSensors ? selectedBuildingModel?.highRiskSensorCount ?? 0 : 0}</strong></div>
              <div className="metric"><span>AI forecast next 30m</span><strong>{selectedBuildingHasActiveSensors && selectedBuildingModel ? `${selectedBuildingModel.forecastMw.toFixed(2)} MW` : '--'}</strong></div>
            </div>

            <div className="building-modal__toolbar"><button className="ghost-button ghost-button--accent" onClick={beginAddSensorMode} type="button">Add node</button></div>
            {sensorToggleError ? <div className="form-error">{sensorToggleError}</div> : null}

            {addSensorMode && draftSensor ? (
              <article className="panel panel--composer modal-composer">
                <div className="panel-heading">
                  <div><p className="kicker">Internal Node</p><h2>Add sensor/load</h2></div>
                  <span className="status-badge status-unclaimed">Draft</span>
                </div>
                <div className="composer-form modal-composer__grid">
                  <label><span>Node name</span><input onChange={(event) => setDraftSensor((current) => current ? { ...current, name: event.target.value } : current)} value={draftSensor.name} /></label>
                  <label><span>Active load (MW)</span><input min="0" onChange={(event) => setDraftSensor((current) => current ? { ...current, pMw: event.target.value } : current)} step="0.01" type="number" value={draftSensor.pMw} /></label>
                  <label><span>Reactive load (MVAR)</span><input min="0" onChange={(event) => setDraftSensor((current) => current ? { ...current, qMvar: event.target.value } : current)} step="0.01" type="number" value={draftSensor.qMvar} /></label>
                </div>
                {saveSensorError ? <div className="form-error">{saveSensorError}</div> : null}
                <div className="composer-actions">
                  <button disabled={saveSensorBusy || !draftSensor.name.trim()} onClick={() => void handleSaveSensor()} type="button">{saveSensorBusy ? 'Saving node...' : 'Save node'}</button>
                  <button className="ghost-button" onClick={cancelAddSensor} type="button">Cancel</button>
                </div>
              </article>
            ) : null}

            <div className="building-modal__content">
              <div className="modal-side">
                <article className="panel">
                  <div className="detail-list">
                    <div><span>Hardware ID</span><strong>{selectedBuilding.hardwareId}</strong></div>
                    <div><span>Bus</span><strong>{selectedBuilding.busId}</strong></div>
                    <div><span>Coordinates</span><strong>{selectedBuilding.lat.toFixed(6)}, {selectedBuilding.lng.toFixed(6)}</strong></div>
                    <div><span>Simulation mode</span><strong>{supervised ? 'Running' : 'Ready to start'}</strong></div>
                    <div><span>AI window</span><strong>{formatLiveWindow(modelInsights.summary.windowSize, modelInsights.summary.windowStart, modelInsights.summary.windowEnd)}</strong></div>
                    <div><span>Model source</span><strong>{liveSourceLabel(modelInsights.summary.source)}</strong></div>
                    <div><span>Latest tick</span><strong>{simulationUpdatedAt ? formatClock(simulationUpdatedAt) : '--'}</strong></div>
                    <div><span>Top issue</span><strong>{selectedBuildingHasActiveSensors ? selectedBuildingModel?.topIssue ?? 'Window stable' : 'All sensors turned off'}</strong></div>
                  </div>
                  {renderClaimBox(selectedBuilding)}
                </article>
              </div>

              <div className="modal-main">
                <div className="sensor-section sensor-section--modal">
                  <p className="kicker">All Internal Sensors</p>
                  <div className="sensor-list sensor-list--modal">
                    {selectedBuilding.sensors.map((sensor) => {
                      const sensorModel = modelInsights.sensors[sensor.sensorId]
                      const latestPoint = sensorHistory[sensor.sensorId]?.[sensorHistory[sensor.sensorId].length - 1]
                      return (
                        <article className={`sensor-card sensor-card--modal sensor-card--${sensor.status}`} key={sensor.id}>
                          <div className="sensor-card__header sensor-card__header--split">
                            <div><strong>{sensor.name}</strong><span>{sensor.sensorId}</span></div>
                            <div className="sensor-card__badges">
                              <span className={`mini-badge status-${sensor.status}`}>{statusLabel(sensor.status)}</span>
                              {sensor.isActive && sensorModel ? <span className={`mini-badge model-badge model-badge--${modelToneClass(sensorModel.label)}`}>{modelLabel(sensorModel.label)}</span> : null}
                            </div>
                          </div>
                          <div className="sensor-card__metrics sensor-card__metrics--grid">
                            <span>Expected: {sensor.expectedMw.toFixed(3)} MW</span>
                            <span>Measured: {sensor.currentMw.toFixed(3)} MW</span>
                            <span>Compare state: {sensor.isActive ? comparisonLabel(sensor.comparisonStatus) : 'Turned off'}</span>
                            <span>Simulated exact: {sensor.comparedExpectedMw !== null ? formatMw(sensor.comparedExpectedMw) : 'Unavailable'}</span>
                            <span>Measured exact: {sensor.comparedActualMw !== null ? formatMw(sensor.comparedActualMw) : 'No reading'}</span>
                            <span>Delta: {sensor.deltaMw !== null ? formatSignedMw(sensor.deltaMw) : 'Not comparable'}</span>
                            <span>Sensor index: {sensor.sensorIndex}</span>
                          </div>
                          <div className="sensor-stream-row">
                            <span className={`signal-dot signal-dot--${sensor.status}`} />
                            <span>{sensor.isActive ? latestPoint ? `Sensor packet ${formatClock(latestPoint.timestamp)}` : 'Awaiting first packet' : 'Sensor manually turned off'}</span>
                            <span>{sensor.isActive && latestPoint ? `${latestPoint.voltageV.toFixed(1)} V` : '--'}</span>
                            <span>{sensor.isActive && latestPoint ? `${latestPoint.currentA.toFixed(2)} A` : '--'}</span>
                          </div>
                          <div className="telemetry-chip-row">
                            {buildTelemetryChips(latestPoint, sensor.isActive).map((chip) => (
                              <span className={`telemetry-chip telemetry-chip--${chip.tone}`} key={chip.label}>{chip.label}</span>
                            ))}
                          </div>

                          {selectedBuilding.claimedByCurrentUser ? (
                            <div className="sensor-card__actions">
                              <button
                                className={`ghost-button ${sensor.isActive ? 'ghost-button--danger' : 'ghost-button--accent'}`}
                                disabled={sensorToggleBusyId === sensor.id}
                                onClick={() => void handleSetSensorActive(sensor.id, !sensor.isActive)}
                                type="button"
                              >
                                {sensorToggleBusyId === sensor.id ? sensor.isActive ? 'Turning off...' : 'Turning on...' : sensor.isActive ? 'Turn Off' : 'Turn On'}
                              </button>
                            </div>
                          ) : null}

                          {sensor.isActive && sensorModel ? (
                            <div className="model-box">
                              <div className="model-box__header">
                                <strong>AI model window</strong>
                                <span>{formatPercent(sensorModel.confidence)} prediction strength</span>
                              </div>
                              <div className="sensor-card__metrics sensor-card__metrics--grid">
                                <span>Anomaly score: {formatPercent(sensorModel.anomalyScore)}</span>
                                <span>Forecast next 30m: {sensorModel.forecastMw.toFixed(3)} MW</span>
                                <span>Voltage now: {sensorModel.currentVoltageV.toFixed(1)} V</span>
                                <span>Current now: {sensorModel.currentCurrentA.toFixed(2)} A</span>
                              </div>
                              <div className="history-strip" aria-label="Recent model input history">
                                {sensorModel.history.map((point) => (
                                  <div className="history-strip__item" key={point.timestamp}>
                                    <span className="history-strip__label">{formatWindowTick(point.timestamp)}</span>
                                    <span className="history-strip__bar" style={{ height: `${Math.max(16, point.powerMw / Math.max(sensorModel.forecastMw, 0.05) * 72)}px` }} />
                                    <span className="history-strip__value">{point.powerMw.toFixed(3)} MW</span>
                                  </div>
                                ))}
                              </div>
                              <p className="model-box__reason">{sensorModel.reason}</p>
                            </div>
                          ) : null}

                          {selectedBuilding.claimedByCurrentUser && supervised && (sensor.status === 'watch' || sensor.status === 'critical') ? (
                            <div className="review-box review-box--panel">
                              <strong>Operator decision</strong>
                              <div className="review-actions">
                                <button onClick={() => markSensorReview(sensor.id, 'normal')} type="button">Mark normal</button>
                                <button onClick={() => markSensorReview(sensor.id, 'anomaly')} type="button">Keep issue</button>
                                {sensor.reviewDecision ? <button className="ghost-button" onClick={() => clearSensorReview(sensor.id)} type="button">Clear review</button> : null}
                              </div>
                            </div>
                          ) : null}
                        </article>
                      )
                    })}
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>
      ) : null}
    </main>
  )
}

function MapPlacementHandler({ active, onPlace }: { active: boolean; onPlace: (lat: number, lng: number) => void }) {
  useMapEvents({
    click(event) {
      if (active) onPlace(event.latlng.lat, event.latlng.lng)
    },
  })
  return null
}

async function superviseBuildings(
  token: string,
  claimedDevices: DeviceRecord[],
  nitwReference: NitwReference,
  readingsPayload?: Record<string, number>,
) {
  const compare = await compareNitwNetwork(
    token,
    filterActiveNetworkPayload(nitwReference),
    readingsPayload && Object.keys(readingsPayload).length
      ? readingsPayload
      : buildReadingsPayload(claimedDevices, nitwReference),
  )
  return mapComparisonsByElementId(compare.comparisons ?? [])
}

function buildReadingsPayload(claimedDevices: DeviceRecord[], nitwReference: NitwReference): Record<string, number> {
  const claimedByHardwareId = new Map(claimedDevices.filter((d) => !d.nodeKind || d.nodeKind === 'building').map((d) => [d.hardwareId, d]))
  const readings: Record<string, number> = {}
  for (const load of nitwReference.loads) {
    if (load.is_active === false) continue
    const buildingId = load.building_id ?? `building_${slugify(load.name || load.id || load.bus_id)}`
    const device = claimedByHardwareId.get(hardwareIdForBuildingId(buildingId))
    const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
    const latest = device?.latestReadings.find((reading) => reading.sensorId === sensorId)
    readings[sensorId] = typeof latest?.value === 'number' ? latest.value : fakeReadingForLoad(load)
  }
  return readings
}

function mapComparisonsByElementId(comparisons: ComparisonRecord[]) {
  return Object.fromEntries(
    comparisons
      .filter((entry) => entry.element_type === 'load')
      .map((entry) => [entry.element_id, entry]),
  ) as Record<string, ComparisonRecord>
}

function seedSimulatedReadings(
  claimedDevices: DeviceRecord[],
  nitwReference: NitwReference,
  currentReadings: Record<string, number>,
) {
  const fallbackReadings = buildReadingsPayload(claimedDevices, nitwReference)
  const nextReadings: Record<string, number> = {}

  for (const [sensorId, value] of Object.entries(fallbackReadings)) {
    nextReadings[sensorId] = typeof currentReadings[sensorId] === 'number' ? currentReadings[sensorId] : value
  }

  return nextReadings
}

function seedSensorHistory(
  nitwReference: NitwReference,
  readings: Record<string, number>,
  currentHistory: Record<string, SensorHistoryPoint[]>,
  timestamp: string,
) {
  return advanceSensorHistory(nitwReference, readings, currentHistory, timestamp)
}

function applyLiveTelemetryPacket(
  nitwReference: NitwReference,
  packet: Extract<LiveFeedEvent, { type: 'telemetry_packet' }>,
  currentReadings: Record<string, number>,
  currentHistory: Record<string, SensorHistoryPoint[]>,
) {
  const loadBySensorId = new Map(
    nitwReference.loads.map((load) => {
      const sensorId = nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ?? `sensor_${load.id}`
      return [sensorId, load] as const
    }),
  )
  const nextReadings = { ...currentReadings }
  const nextHistory = { ...currentHistory }
  const packetTimestamp = packet.serverTimestamp || new Date().toISOString()

  for (const update of packet.updates) {
    const load = loadBySensorId.get(update.sensorId)
    if (!load || load.is_active === false) continue
    const powerMw = typeof update.value === 'number' ? update.value : numberOrNull(update.metadata.powerMw) ?? Math.max(load.p_mw, 0.01)
    nextReadings[update.sensorId] = Number(powerMw.toFixed(4))
    const currentWindow = nextHistory[update.sensorId] ?? []
    const nextPoint = buildLiveHistoryPoint(
      update.sensorId,
      load.p_mw,
      powerMw,
      currentWindow.length,
      packetTimestamp,
      update.metadata,
    )
    nextHistory[update.sensorId] = [...currentWindow, nextPoint].slice(-SENSOR_HISTORY_LIMIT)
  }

  return {
    readings: nextReadings,
    history: nextHistory,
    updatedAt: packetTimestamp,
  }
}

function advanceSensorHistory(
  nitwReference: NitwReference,
  readings: Record<string, number>,
  currentHistory: Record<string, SensorHistoryPoint[]>,
  timestamp: string,
) {
  const sensorByLoadId = new Map(
    nitwReference.sensor_links
      .filter((link) => link.element_type === 'load')
      .map((link) => [link.element_id, link.sensor_id]),
  )
  const nextHistory: Record<string, SensorHistoryPoint[]> = {}

  for (const load of nitwReference.loads) {
    if (load.is_active === false) continue
    const sensorId = sensorByLoadId.get(load.id) ?? `sensor_${load.id}`
    const currentWindow = currentHistory[sensorId] ?? []
    const powerMw = readings[sensorId] ?? Math.max(load.p_mw, 0.01)
    const nextPoint = buildSensorHistoryPoint(sensorId, load.p_mw, powerMw, currentWindow.length, timestamp)
    nextHistory[sensorId] = [...currentWindow, nextPoint].slice(-SENSOR_HISTORY_LIMIT)
  }

  return nextHistory
}

function buildLiveHistoryPoint(
  sensorId: string,
  expectedMw: number,
  powerMw: number,
  index: number,
  timestamp: string,
  metadata: Record<string, unknown>,
): SensorHistoryPoint {
  const voltageV = numberOrNull(metadata.voltageV)
  const currentA = numberOrNull(metadata.currentA)
  const signalStrengthDbm = numberOrNull(metadata.signalStrength)
  const simulatorLabel = typeof metadata.label === 'string' ? metadata.label : null
  const streamId = typeof metadata.streamId === 'string' ? metadata.streamId : null
  const anomalyFrame = metadata.isAnomaly === true || metadata.isAnomaly === 1 || metadata.isAnomaly === '1'
  const simulated = metadata.simulated === true
  if (voltageV !== null && currentA !== null) {
    return {
      timestamp,
      powerMw: Number(powerMw.toFixed(4)),
      voltageV: Number(voltageV.toFixed(1)),
      currentA: Number(currentA.toFixed(2)),
      signalStrengthDbm,
      simulated,
      simulatorLabel,
      anomalyFrame,
      streamId,
    }
  }
  return {
    ...buildSensorHistoryPoint(sensorId, expectedMw, powerMw, index, timestamp),
    signalStrengthDbm,
    simulated,
    simulatorLabel,
    anomalyFrame,
    streamId,
  }
}

function buildSensorHistoryPoint(
  sensorId: string,
  expectedMw: number,
  powerMw: number,
  index: number,
  timestamp: string,
): SensorHistoryPoint {
  const baseExpected = Math.max(expectedMw, 0.01)
  const ratio = powerMw / baseExpected
  const checksum = stableNumber(sensorId)
  const oscillation = Math.sin(index / 2.3 + checksum / 17) * 5.5
  let voltageV = 414 - (ratio - 1) * 36 + oscillation
  if (ratio < 0.35) voltageV -= 120
  if (ratio > 1.22) voltageV -= 18
  const boundedVoltage = clamp(voltageV, 45, 452)
  return {
    timestamp,
    powerMw: Number(powerMw.toFixed(4)),
    voltageV: Number(boundedVoltage.toFixed(1)),
    currentA: Number((((powerMw * 1_000_000) / (Math.sqrt(3) * Math.max(boundedVoltage, 1) * 0.92))).toFixed(2)),
  }
}

function buildNetworkWithDraftBuilding(nitwReference: NitwReference, draftBuilding: DraftBuilding) {
  const name = draftBuilding.name.trim()
  const firstSensorName = draftBuilding.firstSensorName.trim()
  if (!name) throw new Error('Building name is required')
  if (!firstSensorName) throw new Error('First node name is required')
  const buildings = normalizedBuildings(nitwReference)
  const buildingId = buildUniqueId(`building_${slugify(name)}`, buildings.map((building) => building.id))
  const busId = buildUniqueId(`bus_${slugify(name)}`, nitwReference.buses.map((bus) => bus.id))
  const loadId = buildUniqueId(`load_${slugify(name)}_01`, nitwReference.loads.map((load) => load.id))
  const sensorId = buildUniqueId(`sensor_${slugify(name)}_01`, nitwReference.sensor_links.map((link) => link.sensor_id))
  const pMw = Number(draftBuilding.pMw)
  const qMvar = Number(draftBuilding.qMvar)
  const vnKv = Number(draftBuilding.vnKv)
  if (!Number.isFinite(pMw) || pMw < 0) throw new Error('Active load must be a valid non-negative number')
  if (!Number.isFinite(qMvar) || qMvar < 0) throw new Error('Reactive load must be a valid non-negative number')
  if (!Number.isFinite(vnKv) || vnKv <= 0) throw new Error('Bus voltage must be a valid positive number')
  return {
    buildingId,
    networkPayload: {
      ...nitwReference,
      buildings: [...buildings, { id: buildingId, name, bus_id: busId, lat: draftBuilding.lat, long: draftBuilding.lng, gateway_hardware_id: hardwareIdForBuildingId(buildingId), sensor_count: 1, p_mw: pMw, q_mvar: qMvar }],
      buses: [...nitwReference.buses, { id: busId, name: `Bus ${name}`, vn_kv: vnKv, type: 'b' }],
      loads: [...nitwReference.loads, { id: loadId, name: firstSensorName, bus_id: busId, building_id: buildingId, sensor_index: 1, is_active: true, p_mw: pMw, q_mvar: qMvar, lat: draftBuilding.lat, long: draftBuilding.lng }],
      sensor_links: [...nitwReference.sensor_links, { sensor_id: sensorId, element_type: 'load', element_id: loadId, measurement: 'p_mw' }],
    },
  }
}

function buildNetworkWithAddedSensor(nitwReference: NitwReference, building: CampusBuilding, draftSensor: DraftSensor): NitwReference {
  const name = draftSensor.name.trim()
  if (!name) throw new Error('Node name is required')
  const pMw = Number(draftSensor.pMw)
  const qMvar = Number(draftSensor.qMvar)
  if (!Number.isFinite(pMw) || pMw < 0) throw new Error('Active load must be a valid non-negative number')
  if (!Number.isFinite(qMvar) || qMvar < 0) throw new Error('Reactive load must be a valid non-negative number')
  const sensorIndex = building.sensorCount + 1
  const suffix = String(sensorIndex).padStart(2, '0')
  const loadId = buildUniqueId(`load_${slugify(building.name)}_${suffix}`, nitwReference.loads.map((load) => load.id))
  const sensorId = buildUniqueId(`sensor_${slugify(building.name)}_${suffix}`, nitwReference.sensor_links.map((link) => link.sensor_id))
  return {
    ...nitwReference,
    buildings: normalizedBuildings(nitwReference),
    loads: [...nitwReference.loads, { id: loadId, name, bus_id: building.busId, building_id: building.id, sensor_index: sensorIndex, is_active: true, p_mw: pMw, q_mvar: qMvar, lat: building.lat, long: building.lng }],
    sensor_links: [...nitwReference.sensor_links, { sensor_id: sensorId, element_type: 'load', element_id: loadId, measurement: 'p_mw' }],
  }
}

function buildNetworkWithSensorActivity(
  nitwReference: NitwReference,
  sensorNodeId: string,
  nextIsActive: boolean,
): NitwReference {
  return {
    ...nitwReference,
    buildings: normalizedBuildings(nitwReference),
    loads: nitwReference.loads.map((load) => load.id === sensorNodeId ? { ...load, is_active: nextIsActive } : load),
  }
}

function filterActiveNetworkPayload(nitwReference: NitwReference): NitwReference {
  const activeLoadIds = new Set(
    nitwReference.loads
      .filter((load) => load.is_active !== false)
      .map((load) => load.id),
  )
  return {
    ...nitwReference,
    buildings: normalizedBuildings(nitwReference),
    loads: nitwReference.loads.filter((load) => activeLoadIds.has(load.id)),
    sensor_links: nitwReference.sensor_links.filter((link) => link.element_type !== 'load' || activeLoadIds.has(link.element_id)),
  }
}

function normalizedBuildings(nitwReference: NitwReference): NonNullable<NitwReference['buildings']> {
  return nitwReference.buildings?.length ? nitwReference.buildings : deriveBuildingsFromLoads(nitwReference)
}

function deriveBuildingsFromLoads(nitwReference: NitwReference): NonNullable<NitwReference['buildings']> {
  const buildingsById = new Map<string, NonNullable<NitwReference['buildings']>[number]>()
  for (const load of nitwReference.loads) {
    const buildingId = load.building_id ?? `building_${slugify(load.name || load.id || load.bus_id)}`
    if (!buildingsById.has(buildingId)) {
      buildingsById.set(buildingId, { id: buildingId, name: (load.name || buildingId).split(' Sensor ')[0], bus_id: load.bus_id, lat: load.lat, long: load.long, gateway_hardware_id: hardwareIdForBuildingId(buildingId), sensor_count: 0, p_mw: 0, q_mvar: 0 })
    }
    const current = buildingsById.get(buildingId)
    if (!current) continue
    current.sensor_count = (current.sensor_count ?? 0) + 1
    current.p_mw = (current.p_mw ?? 0) + load.p_mw
    current.q_mvar = (current.q_mvar ?? 0) + load.q_mvar
  }
  return Array.from(buildingsById.values())
}

function createInitialDraftBuilding(): DraftBuilding {
  return { name: '', lat: 17.98369646253154, lng: 79.53082786635768, firstSensorName: 'Main panel sensor', pMw: '0.10', qMvar: '0.04', vnKv: '20' }
}

function fakeReadingForLoad(load: NitwReference['loads'][number] | undefined) {
  if (!load) return 0
  const checksum = Array.from(load.id).reduce((total, character) => total + character.charCodeAt(0), 0)
  return Number((load.p_mw * (1 + (((checksum % 9) - 4) * 0.0125))).toFixed(4))
}

function countSensorsByStatus(sensors: BuildingSensor[], status: VisualStatus) {
  return sensors.filter((sensor) => sensor.status === status).length
}

function comparisonVisualStatus(status: string | null): VisualStatus {
  if (!status || status === 'match') return 'good'
  if (status === 'inactive') return 'offline'
  if (status === 'deviation') return 'watch'
  return 'critical'
}

function sensorModelVisualStatus(
  sensorModel: SensorModelInsight | undefined,
  reviewDecision: SensorReviewDecision | null,
): VisualStatus {
  if (reviewDecision === 'normal') return 'good'
  if (reviewDecision === 'anomaly') return sensorModel?.label === 'outage' ? 'critical' : 'watch'
  if (!sensorModel) return 'good'
  if (sensorModel.label === 'outage') return 'critical'
  if (sensorModel.label === 'overload' && sensorModel.anomalyScore >= 0.78) return 'critical'
  if (sensorModel.anomalyScore >= 0.85) return 'critical'
  if (sensorModel.label !== 'stable' && sensorModel.anomalyScore >= 0.55) return 'watch'
  if (sensorModel.anomalyScore >= 0.48) return 'watch'
  return 'good'
}

function summarizeSensorStatuses(sensors: BuildingSensor[]) {
  if (!sensors.some((sensor) => sensor.isActive)) return 'offline'
  if (sensors.some((sensor) => sensor.status === 'critical')) return 'critical'
  if (sensors.some((sensor) => sensor.status === 'watch')) return 'watch'
  if (sensors.every((sensor) => sensor.status === 'unclaimed' || sensor.status === 'offline')) return 'unclaimed'
  return 'good'
}

function maxVisualStatus(...statuses: VisualStatus[]) {
  return [...statuses].sort((left, right) => visualStatusRank(right) - visualStatusRank(left))[0] ?? 'good'
}

function visualStatusRank(status: VisualStatus) {
  return {
    offline: 0,
    unclaimed: 1,
    good: 2,
    watch: 3,
    critical: 4,
  }[status]
}

function resolveSensorVisualStatus(
  sensor: BuildingSensor,
  sensorModel: SensorModelInsight | undefined,
): VisualStatus {
  if (!sensor.isActive) return 'offline'
  if (sensor.status === 'unclaimed') return 'unclaimed'
  return maxVisualStatus(
    sensor.status,
    comparisonVisualStatus(sensor.comparisonStatus),
    sensorModelVisualStatus(sensorModel, sensor.reviewDecision),
  )
}

function resolveBuildingVisualStatus(
  currentStatus: VisualStatus,
  sensors: BuildingSensor[],
  buildingModel: BuildingModelInsight | undefined,
): VisualStatus {
  if (currentStatus === 'unclaimed') return 'unclaimed'
  if (!sensors.some((sensor) => sensor.isActive)) return 'offline'
  const sensorStatus = summarizeSensorStatuses(sensors)
  if (sensorStatus === 'critical' || sensorStatus === 'watch') return sensorStatus
  if (buildingModel?.label === 'outage' || (buildingModel?.anomalyScore ?? 0) >= 0.85) return 'critical'
  if (buildingModel && buildingModel.highRiskSensorCount > 0 && buildingModel.anomalyScore >= 0.55) return 'watch'
  return 'good'
}

function fillColor(status: VisualStatus) { return status === 'good' ? '#64d7a1' : status === 'watch' ? '#f5b14c' : status === 'critical' ? '#f09090' : status === 'offline' ? '#c2c8cf' : '#7eb6ff' }
function borderColor(status: VisualStatus) { return status === 'good' ? '#17885c' : status === 'watch' ? '#c57a0e' : status === 'critical' ? '#c44747' : status === 'offline' ? '#6b7480' : '#2e6bd3' }
function edgeColor(status: VisualStatus) { return status === 'good' ? '#1b9f6e' : status === 'watch' ? '#dc8d1c' : status === 'critical' ? '#d74b4b' : status === 'offline' ? '#7a828d' : '#2c70d8' }
function statusLabel(status: VisualStatus) { return status === 'good' ? 'All Good' : status === 'watch' ? 'OK OK' : status === 'critical' ? 'Serious Issue' : status === 'offline' ? 'Turned Off' : 'Unclaimed' }
function statusColorLabel(status: VisualStatus) { return status === 'good' ? 'Green' : status === 'watch' ? 'Orange' : status === 'critical' ? 'Red' : status === 'offline' ? 'Grey' : 'Blue' }

function comparisonLabel(status: string | null) {
  if (!status) return 'Simulation ready'
  if (status === 'inactive') return 'Turned off'
  if (status === 'topology_issue') return 'Topology issue'
  if (status === 'missing_actual') return 'Missing sensor value'
  if (status === 'missing_expected') return 'Missing simulation value'
  if (status === 'match') return 'Aligned'
  if (status === 'deviation') return 'Needs attention'
  return status
}

function modelLabel(label: string) {
  if (label === 'stable') return 'AI Stable'
  if (label === 'sensor_fault') return 'AI Sensor Fault'
  if (label === 'undervoltage') return 'AI Undervoltage'
  if (label === 'overload') return 'AI Overload'
  if (label === 'outage') return 'AI Outage'
  return label
}

function modelToneClass(label: string) {
  if (label === 'stable') return 'stable'
  if (label === 'sensor_fault') return 'warning'
  if (label === 'undervoltage') return 'warning'
  if (label === 'overload') return 'danger'
  if (label === 'outage') return 'danger'
  return 'stable'
}

function buildTelemetryChips(point: SensorHistoryPoint | undefined, active = true) {
  const chips: Array<{ label: string; tone: 'good' | 'watch' | 'critical' | 'neutral' }> = []

  if (!active) {
    chips.push({ label: 'Sensor turned off', tone: 'neutral' })
    return chips
  }

  if (!point) {
    chips.push({ label: 'Waiting for sensor packet', tone: 'neutral' })
    return chips
  }

  chips.push({
    label: point.simulated ? 'Simulated sensor packet' : 'Live sensor packet',
    tone: point.anomalyFrame ? 'critical' : 'neutral',
  })

  if (typeof point.signalStrengthDbm === 'number') {
    chips.push({
      label: `RSSI ${point.signalStrengthDbm} dBm`,
      tone: point.signalStrengthDbm <= -82 ? 'watch' : 'good',
    })
  }

  if (point.simulatorLabel) {
    chips.push({
      label: telemetryLabel(point.simulatorLabel),
      tone: point.anomalyFrame ? 'critical' : 'neutral',
    })
  }

  if (point.streamId) {
    chips.push({
      label: `Stream ${point.streamId}`,
      tone: 'neutral',
    })
  }

  return chips
}

function telemetryLabel(value: string) {
  return value
    .split('_')
    .map((part) => part.charAt(0).toUpperCase() + part.slice(1))
    .join(' ')
}

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function formatClock(value: string) {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatWindowTick(value: string) {
  return new Date(value).toLocaleTimeString([], { minute: '2-digit', second: '2-digit' })
}

function formatLiveWindow(windowSize: number, windowStart?: string, windowEnd?: string) {
  const seconds = windowStart && windowEnd
    ? Math.max(1, Math.round((new Date(windowEnd).getTime() - new Date(windowStart).getTime()) / 1000))
    : windowSize
  return `${windowSize} samples (~${seconds}s)`
}

function formatRelativeTick(value: string) {
  const deltaSeconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000))
  if (deltaSeconds <= 1) return 'just now'
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`
  return `${Math.round(deltaSeconds / 60)}m ago`
}

function liveSourceLabel(source: 'synthetic-window' | 'live-window') {
  return source === 'live-window' ? 'Frontend live sensor window' : 'Bootstrapped startup snapshot'
}

function buildUniqueId(baseId: string, existingIds: string[]) {
  if (!existingIds.includes(baseId)) return baseId
  let counter = 2
  while (existingIds.includes(`${baseId}_${counter}`)) counter += 1
  return `${baseId}_${counter}`
}

function formatMw(value: number) { return `${value.toFixed(4)} MW` }
function formatSignedMw(value: number) { return `${value > 0 ? '+' : ''}${value.toFixed(4)} MW` }
function hardwareIdForBuildingId(buildingId: string | undefined) { return buildingId ? `BLDG-${buildingId.replaceAll('_', '-').toUpperCase()}` : '' }
function slugify(value: string) { return value.toLowerCase().trim().replace(/[^a-z0-9]+/g, '_').replace(/^_+|_+$/g, '') }
function extractSensorIndex(loadId: string) { const match = loadId.match(/_(\d+)$/); return match ? Number(match[1]) : 0 }
function sum(values: number[]) { return values.reduce((total, value) => total + value, 0) }

function buildNotificationDetail(
  sensor: BuildingSensor,
  sensorModel: SensorModelInsight,
) {
  if (sensorModel.label === 'outage') return `Packet power dropped to ${sensor.currentMw.toFixed(3)} MW and the model sees an outage-like event.`
  if (sensorModel.label === 'overload') return `Load is climbing toward ${sensorModel.forecastMw.toFixed(3)} MW with ${formatPercent(sensorModel.confidence)} prediction strength.`
  if (sensorModel.label === 'undervoltage') return `Voltage trend is softening while the node stays active, so the stream is marked as undervoltage risk.`
  if (sensorModel.label === 'sensor_fault') return 'The recent frontend packets are oscillating unusually, so the sensor signal may be noisy or unstable.'
  return 'Node remains inside the expected live band.'
}

function numberOrNull(value: unknown) {
  return typeof value === 'number'
    ? value
    : typeof value === 'string' && value.trim() && Number.isFinite(Number(value))
      ? Number(value)
      : null
}

function stableNumber(value: string) {
  return Array.from(value).reduce((total, character, index) => total + character.charCodeAt(0) * (index + 1), 0)
}

export default App
