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
  claimDevice,
  compareNitwNetwork,
  fetchClaimedDevices,
  fetchInventory,
  fetchNitwReference,
  loginUser,
  registerUser,
  syncNetwork,
  type DeviceRecord,
  type NitwReference,
} from './serviceX'

type AuthMode = 'login' | 'register'
type VisualStatus = 'unclaimed' | 'healthy' | 'deviation'
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

const SESSION_KEY = 'innothon-session'
const CAMPUS_CENTER: LatLngExpression = [17.98369646253154, 79.53082786635768]
const PUMP_STATION: LatLngExpression = [17.98369646253154, 79.53082786635768]
const LIVE_SIMULATION_INTERVAL_MS = 2500
const SENSOR_HISTORY_LIMIT = 12
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
  const liveReadingsRef = useRef<Record<string, number>>({})
  const sensorHistoryRef = useRef<Record<string, SensorHistoryPoint[]>>({})

  useEffect(() => {
    if (session) void loadDashboard(session.token, false)
  }, [session])

  useEffect(() => {
    if (!nitwReference) {
      liveReadingsRef.current = {}
      sensorHistoryRef.current = {}
      setSimulatedReadings({})
      setSensorHistory({})
      setSimulationUpdatedAt('')
      return
    }

    const seededReadings = seedSimulatedReadings(claimedDevices, nitwReference, liveReadingsRef.current)
    const seededAt = new Date().toISOString()
    const seededHistory = seedSensorHistory(nitwReference, seededReadings, sensorHistoryRef.current, seededAt)
    liveReadingsRef.current = seededReadings
    sensorHistoryRef.current = seededHistory
    setSimulatedReadings(seededReadings)
    setSensorHistory(seededHistory)
    setSimulationUpdatedAt(seededAt)
  }, [claimedDevices, nitwReference])

  useEffect(() => {
    if (!session || !nitwReference) return

    let cancelled = false
    let timeoutId: number | undefined

    const runLiveCycle = async () => {
      const cycleTimestamp = new Date().toISOString()
      const nextReadings = simulateRealtimeReadings(nitwReference, liveReadingsRef.current, Date.now())
      const nextHistory = advanceSensorHistory(nitwReference, nextReadings, sensorHistoryRef.current, cycleTimestamp)
      liveReadingsRef.current = nextReadings
      sensorHistoryRef.current = nextHistory

      if (!cancelled) {
        setSimulatedReadings(nextReadings)
        setSensorHistory(nextHistory)
        setSimulationUpdatedAt(cycleTimestamp)
      }

      try {
        const compare = await compareNitwNetwork(session.token, nitwReference, nextReadings)
        if (cancelled) return
        setCompareByElementId(mapComparisonsByElementId(compare.comparisons ?? []))
        setSupervised(true)
        setPageError('')
      } catch (error) {
        if (cancelled) return
        setPageError(error instanceof Error ? `Live supervision paused: ${error.message}` : 'Live supervision paused')
      } finally {
        if (!cancelled) {
          timeoutId = window.setTimeout(() => {
            void runLiveCycle()
          }, LIVE_SIMULATION_INTERVAL_MS)
        }
      }
    }

    void runLiveCycle()

    return () => {
      cancelled = true
      if (timeoutId) window.clearTimeout(timeoutId)
    }
  }, [nitwReference, session])

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
        const latest = readingBySensorId.get(sensorId)
        const currentMw = typeof simulatedReadings[sensorId] === 'number'
          ? simulatedReadings[sensorId]
          : typeof latest?.value === 'number'
            ? latest.value
            : fakeReadingForLoad(load)
        const comparison = compareByElementId[load.id]
        const reviewDecision = reviewBySensorId[load.id] ?? null
        let status: VisualStatus = 'unclaimed'
        if (claimedDevice && supervised) status = isProblemComparisonStatus(comparison?.status ?? null) ? 'deviation' : 'healthy'
        if (reviewDecision === 'normal') status = 'healthy'
        return {
          id: load.id,
          name: load.name,
          sensorId,
          sensorIndex: load.sensor_index ?? extractSensorIndex(load.id),
          expectedMw: load.p_mw ?? 0,
          currentMw,
          comparedExpectedMw: comparison?.expected ?? null,
          comparedActualMw: comparison?.actual ?? null,
          deltaMw: comparison?.delta ?? null,
          comparisonStatus: comparison?.status ?? null,
          reviewDecision,
          status,
        }
      }).sort((a, b) => a.sensorIndex - b.sensorIndex || a.name.localeCompare(b.name))
      const buildingStatus: VisualStatus =
        claimedDevice && supervised && sensors.some((s) => s.status === 'deviation')
          ? 'deviation'
          : claimedDevice && supervised
            ? 'healthy'
            : 'unclaimed'
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
      sensors: building.sensors.map((sensor) => ({
        id: sensor.id,
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
      status: resolveSensorVisualStatus(sensor, modelInsights.sensors[sensor.id]),
    }))
    return {
      ...building,
      sensors: nextSensors,
      status: resolveBuildingVisualStatus(building.status, nextSensors, modelInsights.buildings[building.id]),
    }
  }), [baseBuildings, modelInsights])
  const selectedBuilding = buildings.find((b) => b.id === selectedBuildingId) ?? buildings[0] ?? null
  const selectedBuildingModel = selectedBuilding ? modelInsights.buildings[selectedBuilding.id] : null
  const stats = useMemo(() => ({
    claimed: buildings.filter((b) => b.claimedByCurrentUser).length,
    blue: buildings.filter((b) => b.status === 'unclaimed').length,
    red: buildings.filter((b) => b.status === 'deviation').length,
    green: buildings.filter((b) => b.status === 'healthy').length,
    sensors: buildings.reduce((total, b) => total + b.sensorCount, 0),
  }), [buildings])
  const liveNotifications = useMemo<LiveNotification[]>(() => {
    const alerts = buildings.flatMap((building) => building.sensors.flatMap((sensor) => {
      const sensorModel = modelInsights.sensors[sensor.id]
      const lastPacket = sensorHistory[sensor.id]?.[sensorHistory[sensor.id].length - 1]
      const shouldNotify = sensor.status === 'deviation' || (sensorModel && sensorModel.label !== 'stable' && sensorModel.anomalyScore >= 0.55)
      if (!shouldNotify || !sensorModel) return []
      const level: NotificationLevel =
        sensorModel.label === 'outage' || sensorModel.label === 'overload' || sensor.status === 'deviation'
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
        title: 'All sensor nodes streaming',
        detail: `${stats.sensors} nodes reported into the live simulation window with no active anomalies.`,
        timestamp: simulationUpdatedAt,
      }]
      : []
  }, [buildings, modelInsights, sensorHistory, simulationUpdatedAt, stats.sensors])

  async function loadDashboard(token: string, runSupervision: boolean) {
    setPageBusy(true)
    setPageError('')
    try {
      const [inventoryData, claimedData, nitwData] = await Promise.all([fetchInventory(token), fetchClaimedDevices(token), fetchNitwReference(token)])
      const nextSeededReadings = seedSimulatedReadings(claimedData, nitwData, liveReadingsRef.current)
      const seededAt = new Date().toISOString()
      const nextSensorHistory = seedSensorHistory(nitwData, nextSeededReadings, sensorHistoryRef.current, seededAt)
      liveReadingsRef.current = nextSeededReadings
      sensorHistoryRef.current = nextSensorHistory
      setInventory(inventoryData)
      setClaimedDevices(claimedData)
      setNitwReference(nitwData)
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
      const nextSeededReadings = seedSimulatedReadings(claimedData, nitwData, liveReadingsRef.current)
      const seededAt = new Date().toISOString()
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
      setPageError(error instanceof Error ? error.message : 'Supervision failed')
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

  function openBuildingModal(buildingId: string) {
    setSelectedBuildingId(buildingId)
    setShowBuildingModal(true)
    setAddSensorMode(false)
    setSaveSensorError('')
  }

  function closeBuildingModal() {
    setShowBuildingModal(false)
    setAddSensorMode(false)
    setSaveSensorError('')
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
    setSimulatedReadings({})
    setSensorHistory({})
    setSimulationUpdatedAt('')
    setCompareByElementId({})
    setSelectedBuildingId('')
    setSupervised(false)
    setReviewBySensorId({})
    setShowBuildingModal(false)
    setAddBuildingMode(false)
    setDraftBuilding(null)
    liveReadingsRef.current = {}
    sensorHistoryRef.current = {}
  }

  function renderClaimBox(building: CampusBuilding) {
    if (building.claimedByCurrentUser) {
      return <div className="claim-success">{supervised ? 'Claimed by you. Live sensor simulation and AI supervision are active.' : 'Claimed by you. Live sensor simulation is starting.'}</div>
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
          <h1>Claim buildings and inspect internal sensor anomalies</h1>
          <p className="header-copy">Signed in as {session.email}</p>
        </div>
        <div className="header-actions">
          <div className="header-stats">
            <div className="header-stat"><span>Claimed buildings</span><strong>{stats.claimed}</strong></div>
            <div className="header-stat"><span>Total buildings</span><strong>{buildings.length}</strong></div>
            <div className="header-stat"><span>Total sensors</span><strong>{stats.sensors}</strong></div>
            <div className="header-stat"><span>Red buildings</span><strong>{stats.red}</strong></div>
            <div className="header-stat"><span>AI flagged sensors</span><strong>{modelInsights.summary.highRiskSensors}</strong></div>
          </div>
          <div className="header-button-row">
            <button className="ghost-button" disabled={pageBusy || saveBuildingBusy} onClick={beginAddBuildingMode} type="button">Add building</button>
            <button className="ghost-button ghost-button--accent" disabled={pageBusy || superviseBusy} onClick={() => void handleSupervise()} type="button">
              {superviseBusy ? 'Supervising...' : 'Supervise'}
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
                    <span>Anomalous sensors: {building.sensors.filter((sensor) => sensor.status === 'deviation').length}</span>
                    <span>AI high-risk sensors: {modelInsights.buildings[building.id]?.highRiskSensorCount ?? 0}</span>
                    <span className={`map-badge map-badge--${building.status}`}>{statusLabel(building.status)}</span>
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
            <div className="metric"><span>Status</span><strong>{pageBusy ? 'Refreshing...' : supervised ? 'Live supervised' : 'Starting live feed'}</strong></div>
            <div className="metric"><span>AI window</span><strong>{modelInsights.summary.windowSize} steps</strong></div>
            <div className="metric"><span>AI source</span><strong>{liveSourceLabel(modelInsights.summary.source)}</strong></div>
            <div className="metric"><span>Last sensor tick</span><strong>{simulationUpdatedAt ? formatClock(simulationUpdatedAt) : '--'}</strong></div>
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
                  <div><strong>{building.name}</strong><span>{building.sensorCount} sensors • {building.expectedMw.toFixed(2)} MW expected</span></div>
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
                <div><span>Sensors</span><strong>{selectedBuilding.sensorCount}</strong></div>
                <div><span>Expected aggregate</span><strong>{selectedBuilding.expectedMw.toFixed(2)} MW</strong></div>
                <div><span>Current aggregate</span><strong>{selectedBuilding.currentMw.toFixed(2)} MW</strong></div>
                <div><span>AI top label</span><strong>{selectedBuildingModel ? modelLabel(selectedBuildingModel.label) : 'Waiting'}</strong></div>
                <div><span>AI risk score</span><strong>{selectedBuildingModel ? formatPercent(selectedBuildingModel.anomalyScore) : '--'}</strong></div>
                <div><span>Forecast next 30m</span><strong>{selectedBuildingModel ? `${selectedBuildingModel.forecastMw.toFixed(2)} MW` : '--'}</strong></div>
              </div>
              <div className="node-preview-list">
                {selectedBuilding.sensors.slice(0, 5).map((sensor) => {
                  const sensorModel = modelInsights.sensors[sensor.id]
                  const latestPoint = sensorHistory[sensor.id]?.[sensorHistory[sensor.id].length - 1]
                  return (
                    <article className={`node-preview node-preview--${sensor.status}`} key={sensor.id}>
                      <div className="node-preview__header">
                        <div>
                          <strong>{sensor.name}</strong>
                          <span>{sensor.sensorId}</span>
                        </div>
                        <span className={`mini-badge model-badge model-badge--${sensorModel ? modelToneClass(sensorModel.label) : 'stable'}`}>
                          {sensorModel ? modelLabel(sensorModel.label) : 'Streaming'}
                        </span>
                      </div>
                      <div className="node-preview__metrics">
                        <span>{sensor.currentMw.toFixed(3)} MW</span>
                        <span>{latestPoint ? `${latestPoint.voltageV.toFixed(0)} V` : '--'}</span>
                        <span>{latestPoint ? formatRelativeTick(latestPoint.timestamp) : 'Awaiting packet'}</span>
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
                <p className="header-copy">{selectedBuilding.sensorCount} internal sensors on {selectedBuilding.busId}</p>
              </div>
              <div className="building-modal__actions">
                <span className={`status-badge status-${selectedBuilding.status}`}>{statusLabel(selectedBuilding.status)}</span>
                <button className="ghost-button" onClick={closeBuildingModal} type="button">Close</button>
              </div>
            </div>

            <div className="building-modal__summary">
              <div className="metric"><span>Expected aggregate</span><strong>{selectedBuilding.expectedMw.toFixed(2)} MW</strong></div>
              <div className="metric"><span>Current aggregate</span><strong>{selectedBuilding.currentMw.toFixed(2)} MW</strong></div>
              <div className="metric"><span>Anomalous sensors</span><strong>{selectedBuilding.sensors.filter((sensor) => sensor.status === 'deviation').length}</strong></div>
              <div className="metric"><span>Claim count</span><strong>{selectedBuilding.claimCount}</strong></div>
              <div className="metric"><span>AI high-risk sensors</span><strong>{selectedBuildingModel?.highRiskSensorCount ?? 0}</strong></div>
              <div className="metric"><span>AI forecast next 30m</span><strong>{selectedBuildingModel ? `${selectedBuildingModel.forecastMw.toFixed(2)} MW` : '--'}</strong></div>
            </div>

            <div className="building-modal__toolbar"><button className="ghost-button ghost-button--accent" onClick={beginAddSensorMode} type="button">Add node</button></div>

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
                    <div><span>Supervision</span><strong>{supervised ? 'Live' : 'Starting'}</strong></div>
                    <div><span>AI window</span><strong>{modelInsights.summary.windowSize} samples</strong></div>
                    <div><span>Model source</span><strong>{liveSourceLabel(modelInsights.summary.source)}</strong></div>
                    <div><span>Latest tick</span><strong>{simulationUpdatedAt ? formatClock(simulationUpdatedAt) : '--'}</strong></div>
                    <div><span>Top issue</span><strong>{selectedBuildingModel?.topIssue ?? 'Window stable'}</strong></div>
                  </div>
                  {renderClaimBox(selectedBuilding)}
                </article>
              </div>

              <div className="modal-main">
                <div className="sensor-section sensor-section--modal">
                  <p className="kicker">All Internal Sensors</p>
                  <div className="sensor-list sensor-list--modal">
                    {selectedBuilding.sensors.map((sensor) => {
                      const sensorModel = modelInsights.sensors[sensor.id]
                      const latestPoint = sensorHistory[sensor.id]?.[sensorHistory[sensor.id].length - 1]
                      return (
                        <article className={`sensor-card sensor-card--modal sensor-card--${sensor.status}`} key={sensor.id}>
                          <div className="sensor-card__header sensor-card__header--split">
                            <div><strong>{sensor.name}</strong><span>{sensor.sensorId}</span></div>
                            <div className="sensor-card__badges">
                              <span className={`mini-badge status-${sensor.status}`}>{comparisonLabel(sensor.comparisonStatus)}</span>
                              {sensorModel ? <span className={`mini-badge model-badge model-badge--${modelToneClass(sensorModel.label)}`}>{modelLabel(sensorModel.label)}</span> : null}
                            </div>
                          </div>
                          <div className="sensor-card__metrics sensor-card__metrics--grid">
                            <span>Expected: {sensor.expectedMw.toFixed(3)} MW</span>
                            <span>Measured: {sensor.currentMw.toFixed(3)} MW</span>
                            <span>Simulated exact: {sensor.comparedExpectedMw !== null ? formatMw(sensor.comparedExpectedMw) : 'Unavailable'}</span>
                            <span>Measured exact: {sensor.comparedActualMw !== null ? formatMw(sensor.comparedActualMw) : 'No reading'}</span>
                            <span>Delta: {sensor.deltaMw !== null ? formatSignedMw(sensor.deltaMw) : 'Not comparable'}</span>
                            <span>Sensor index: {sensor.sensorIndex}</span>
                          </div>
                          <div className="sensor-stream-row">
                            <span className={`signal-dot signal-dot--${sensor.status}`} />
                            <span>{latestPoint ? `Live packet ${formatClock(latestPoint.timestamp)}` : 'Awaiting first packet'}</span>
                            <span>{latestPoint ? `${latestPoint.voltageV.toFixed(1)} V` : '--'}</span>
                            <span>{latestPoint ? `${latestPoint.currentA.toFixed(2)} A` : '--'}</span>
                          </div>

                          {sensorModel ? (
                            <div className="model-box">
                              <div className="model-box__header">
                                <strong>AI model window</strong>
                                <span>{formatPercent(sensorModel.confidence)} confidence</span>
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
                                    <span className="history-strip__label">{new Date(point.timestamp).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}</span>
                                    <span className="history-strip__bar" style={{ height: `${Math.max(16, point.powerMw / Math.max(sensorModel.forecastMw, 0.05) * 72)}px` }} />
                                    <span className="history-strip__value">{point.powerMw.toFixed(3)} MW</span>
                                  </div>
                                ))}
                              </div>
                              <p className="model-box__reason">{sensorModel.reason}</p>
                            </div>
                          ) : null}

                          {selectedBuilding.claimedByCurrentUser && supervised && sensor.status === 'deviation' ? (
                            <div className="review-box review-box--panel">
                              <strong>Operator decision</strong>
                              <div className="review-actions">
                                <button onClick={() => markSensorReview(sensor.id, 'normal')} type="button">Mark normal</button>
                                <button onClick={() => markSensorReview(sensor.id, 'anomaly')} type="button">Keep anomaly</button>
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
    nitwReference,
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
    const sensorId = sensorByLoadId.get(load.id) ?? `sensor_${load.id}`
    const currentWindow = currentHistory[sensorId] ?? []
    const powerMw = readings[sensorId] ?? Math.max(load.p_mw, 0.01)
    const nextPoint = buildSensorHistoryPoint(sensorId, load.p_mw, powerMw, currentWindow.length, timestamp)
    nextHistory[sensorId] = [...currentWindow, nextPoint].slice(-SENSOR_HISTORY_LIMIT)
  }

  return nextHistory
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

function simulateRealtimeReadings(
  nitwReference: NitwReference,
  currentReadings: Record<string, number>,
  timestampMs: number,
) {
  const sensorByLoadId = new Map(
    nitwReference.sensor_links
      .filter((link) => link.element_type === 'load')
      .map((link) => [link.element_id, link.sensor_id]),
  )
  const nextReadings: Record<string, number> = {}

  for (const load of nitwReference.loads) {
    const sensorId = sensorByLoadId.get(load.id) ?? `sensor_${load.id}`
    const baseLoad = Math.max(load.p_mw, 0.01)
    const previous = currentReadings[sensorId]
    const checksum = stableNumber(load.id)
    const slowWave = Math.sin(timestampMs / 7000 + checksum / 19)
    const fastWave = Math.cos(timestampMs / 3200 + checksum / 23)
    const bias = ((checksum % 11) - 5) * 0.012
    let nextValue = baseLoad * (1 + bias + slowWave * 0.08 + fastWave * 0.035)

    if (checksum % 9 === 0 && slowWave > 0.82) {
      nextValue = baseLoad * (1.24 + Math.max(fastWave, -0.1) * 0.1)
    } else if (checksum % 13 === 0 && fastWave < -0.72) {
      nextValue = baseLoad * (0.58 + Math.abs(slowWave) * 0.05)
    } else if (checksum % 17 === 0 && Math.sin(timestampMs / 5100 + checksum / 7) > 0.92) {
      nextValue = baseLoad * 0.18
    }

    const smoothedValue = typeof previous === 'number'
      ? previous * 0.42 + nextValue * 0.58
      : nextValue

    nextReadings[sensorId] = Number(clamp(smoothedValue, 0.002, Math.max(baseLoad * 1.65, 0.05)).toFixed(4))
  }

  return nextReadings
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
      loads: [...nitwReference.loads, { id: loadId, name: firstSensorName, bus_id: busId, building_id: buildingId, sensor_index: 1, p_mw: pMw, q_mvar: qMvar, lat: draftBuilding.lat, long: draftBuilding.lng }],
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
    loads: [...nitwReference.loads, { id: loadId, name, bus_id: building.busId, building_id: building.id, sensor_index: sensorIndex, p_mw: pMw, q_mvar: qMvar, lat: building.lat, long: building.lng }],
    sensor_links: [...nitwReference.sensor_links, { sensor_id: sensorId, element_type: 'load', element_id: loadId, measurement: 'p_mw' }],
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

function isProblemComparisonStatus(status: string | null) {
  return status === 'deviation' || status === 'topology_issue' || status === 'missing_actual' || status === 'missing_expected'
}

function resolveSensorVisualStatus(
  sensor: BuildingSensor,
  sensorModel: SensorModelInsight | undefined,
): VisualStatus {
  if (sensor.reviewDecision === 'normal') return 'healthy'
  if (sensor.status === 'unclaimed') return 'unclaimed'
  if (sensor.status === 'deviation') return 'deviation'
  if (sensorModel && sensorModel.label !== 'stable' && sensorModel.anomalyScore >= 0.6) return 'deviation'
  return 'healthy'
}

function resolveBuildingVisualStatus(
  currentStatus: VisualStatus,
  sensors: BuildingSensor[],
  buildingModel: BuildingModelInsight | undefined,
): VisualStatus {
  if (currentStatus === 'unclaimed') return 'unclaimed'
  if (sensors.some((sensor) => sensor.status === 'deviation')) return 'deviation'
  if (buildingModel && buildingModel.highRiskSensorCount > 0 && buildingModel.anomalyScore >= 0.6) return 'deviation'
  return 'healthy'
}

function fillColor(status: VisualStatus) { return status === 'healthy' ? '#64d7a1' : status === 'deviation' ? '#f09090' : '#7eb6ff' }
function borderColor(status: VisualStatus) { return status === 'healthy' ? '#17885c' : status === 'deviation' ? '#c44747' : '#2e6bd3' }
function edgeColor(status: VisualStatus) { return status === 'healthy' ? '#1b9f6e' : status === 'deviation' ? '#d74b4b' : '#2c70d8' }
function statusLabel(status: VisualStatus) { return status === 'healthy' ? 'Healthy' : status === 'deviation' ? 'Deviation' : 'Unclaimed' }

function comparisonLabel(status: string | null) {
  if (!status) return 'Not run yet'
  if (status === 'topology_issue') return 'Topology issue'
  if (status === 'missing_actual') return 'Missing sensor value'
  if (status === 'missing_expected') return 'Missing simulation value'
  if (status === 'match') return 'Match'
  if (status === 'deviation') return 'Deviation'
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

function formatPercent(value: number) {
  return `${Math.round(value * 100)}%`
}

function clamp(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, value))
}

function formatClock(value: string) {
  return new Date(value).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}

function formatRelativeTick(value: string) {
  const deltaSeconds = Math.max(0, Math.round((Date.now() - new Date(value).getTime()) / 1000))
  if (deltaSeconds <= 1) return 'just now'
  if (deltaSeconds < 60) return `${deltaSeconds}s ago`
  return `${Math.round(deltaSeconds / 60)}m ago`
}

function liveSourceLabel(source: 'synthetic-window' | 'live-window') {
  return source === 'live-window' ? 'Rolling live prediction window' : 'Real-time simulated feed'
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
  if (sensorModel.label === 'overload') return `Load is climbing toward ${sensorModel.forecastMw.toFixed(3)} MW with ${formatPercent(sensorModel.confidence)} confidence.`
  if (sensorModel.label === 'undervoltage') return `Voltage trend is softening while the node stays active, so the stream is marked as undervoltage risk.`
  if (sensorModel.label === 'sensor_fault') return 'The recent live packets are oscillating unusually, so the sensor stream may be noisy or unstable.'
  return 'Node remains inside the expected live band.'
}

function stableNumber(value: string) {
  return Array.from(value).reduce((total, character, index) => total + character.charCodeAt(0) * (index + 1), 0)
}

export default App
