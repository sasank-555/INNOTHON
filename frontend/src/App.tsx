import { useEffect, useMemo, useState } from 'react'
import type { FormEvent } from 'react'
import { CircleMarker, MapContainer, Marker, Popup, Polyline, TileLayer, Tooltip, ZoomControl, useMapEvents } from 'react-leaflet'
import { divIcon } from 'leaflet'
import type { LatLngExpression } from 'leaflet'

import './App.css'
import {
  claimDevice,
  compareNitwNetwork,
  fetchClaimedDevices,
  fetchInventory,
  fetchNitwReference,
  loginUser,
  registerUser,
  type DeviceRecord,
  type NitwReference,
  syncNetwork,
} from './serviceX'

type AuthMode = 'login' | 'register'
type NodeVisualStatus = 'unclaimed' | 'healthy' | 'deviation'
type NodeReviewDecision = 'normal' | 'anomaly'

type Session = {
  token: string
  email: string
}

type CampusNode = {
  id: string
  hardwareId: string
  name: string
  lat: number
  lng: number
  busId: string
  sensorId: string
  expectedMw: number
  currentMw: number
  comparedExpectedMw: number | null
  comparedActualMw: number | null
  deltaMw: number | null
  comparisonStatus: string | null
  reviewDecision: NodeReviewDecision | null
  claimCount: number
  claimedByCurrentUser: boolean
  status: NodeVisualStatus
  claimPasswordHint: string
}

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

type DraftNode = {
  name: string
  lat: number
  lng: number
  pMw: string
  qMvar: string
  vnKv: string
}

const SESSION_KEY = 'innothon-session'
const CAMPUS_CENTER: LatLngExpression = [17.98369646253154, 79.53082786635768]
const PUMP_STATION: LatLngExpression = [17.98369646253154, 79.53082786635768]
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
  const [compareByElementId, setCompareByElementId] = useState<Record<string, ComparisonRecord>>({})
  const [selectedHardwareId, setSelectedHardwareId] = useState<string>('')
  const [claimPasswords, setClaimPasswords] = useState<Record<string, string>>({})
  const [claimErrorByHardwareId, setClaimErrorByHardwareId] = useState<Record<string, string>>({})
  const [claimBusyHardwareId, setClaimBusyHardwareId] = useState<string | null>(null)
  const [pageError, setPageError] = useState('')
  const [pageBusy, setPageBusy] = useState(false)
  const [superviseBusy, setSuperviseBusy] = useState(false)
  const [supervised, setSupervised] = useState(false)
  const [addNodeMode, setAddNodeMode] = useState(false)
  const [draftNode, setDraftNode] = useState<DraftNode | null>(null)
  const [saveNodeBusy, setSaveNodeBusy] = useState(false)
  const [saveNodeError, setSaveNodeError] = useState('')
  const [reviewByNodeId, setReviewByNodeId] = useState<Record<string, NodeReviewDecision>>({})

  useEffect(() => {
    if (!session) {
      return
    }

    void loadDashboard(session.token, false)
  }, [session])

  const nodes = useMemo<CampusNode[]>(() => {
    if (!nitwReference) {
      return []
    }

    const inventoryByHardwareId = new Map(inventory.map((device) => [device.hardwareId, device]))
    const claimedByHardwareId = new Map(claimedDevices.map((device) => [device.hardwareId, device]))
    const linkByElementId = new Map(
      nitwReference.sensor_links
        .filter((link) => link.element_type === 'load')
        .map((link) => [link.element_id, link.sensor_id]),
    )

    return nitwReference.loads
      .map((load) => {
        const hardwareId = hardwareIdForLoadId(load.id)
        const inventoryDevice = inventoryByHardwareId.get(hardwareId)
        const sensorId = linkByElementId.get(load.id) ?? inventoryDevice?.sensorManifest[0]?.sensorId ?? ''
        const claimedDevice = claimedByHardwareId.get(hardwareId)
        const latestReading = claimedDevice?.latestReadings[0]
        const expectedMw = load.p_mw ?? 0
        const currentMw = typeof latestReading?.value === 'number' ? latestReading.value : fakeReadingForLoad(load)
        const comparisonStatus = compareByElementId[load.id]
        const comparedExpectedMw = comparisonStatus?.expected ?? null
        const comparedActualMw = comparisonStatus?.actual ?? null
        const deltaMw = comparisonStatus?.delta ?? null
        const reviewDecision = reviewByNodeId[load.id] ?? null
        const claimedByCurrentUser = Boolean(claimedDevice)

        let status: NodeVisualStatus = 'unclaimed'
        if (claimedByCurrentUser && supervised) {
          status = comparisonStatus?.status === 'deviation' || comparisonStatus?.status === 'topology_issue' ? 'deviation' : 'healthy'
        }
        if (reviewDecision === 'normal') {
          status = 'healthy'
        }

        return {
          id: load.id,
          hardwareId,
          name: load.name || inventoryDevice?.displayName || hardwareId,
          lat: load.lat ?? inventoryDevice?.latitude ?? 0,
          lng: load.long ?? inventoryDevice?.longitude ?? 0,
          busId: load.bus_id ?? '',
          sensorId,
          expectedMw,
          currentMw,
          comparedExpectedMw,
          comparedActualMw,
          deltaMw,
          comparisonStatus: comparisonStatus?.status ?? null,
          reviewDecision,
          claimCount: inventoryDevice?.claimCount ?? 0,
          claimedByCurrentUser,
          status,
          claimPasswordHint: `claim-${load.id}`,
        }
      })
      .sort((left, right) => left.name.localeCompare(right.name))
  }, [claimedDevices, compareByElementId, inventory, nitwReference, reviewByNodeId, supervised])

  const selectedNode = nodes.find((node) => node.hardwareId === selectedHardwareId) ?? nodes[0] ?? null

  const stats = useMemo(() => {
    const claimed = nodes.filter((node) => node.claimedByCurrentUser).length
    const blue = nodes.filter((node) => node.status === 'unclaimed').length
    const red = nodes.filter((node) => node.status === 'deviation').length
    const green = nodes.filter((node) => node.status === 'healthy').length
    return { claimed, blue, red, green }
  }, [nodes])

  async function loadDashboard(token: string, runSupervision: boolean) {
    setPageBusy(true)
    setPageError('')
    try {
      const [inventoryData, claimedData, nitwData] = await Promise.all([
        fetchInventory(token),
        fetchClaimedDevices(token),
        fetchNitwReference(token),
      ])

      setInventory(inventoryData)
      setClaimedDevices(claimedData)
      setNitwReference(nitwData)
      setSelectedHardwareId((current) => current || hardwareIdForLoadId(nitwData.loads[0]?.id) || inventoryData[0]?.hardwareId || '')

      if (!runSupervision) {
        setCompareByElementId({})
        setSupervised(false)
        return
      }

      const comparisonIndex = await superviseNodes(token, inventoryData, claimedData, nitwData)
      setCompareByElementId(comparisonIndex)
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
      const result =
        authMode === 'register' ? await registerUser(email.trim(), password) : await loginUser(email.trim(), password)
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
    if (!session) {
      return
    }

    const claimPassword = claimPasswords[hardwareId]?.trim()
    if (!claimPassword) {
      setClaimErrorByHardwareId((current) => ({
        ...current,
        [hardwareId]: 'Enter the node password to claim it.',
      }))
      return
    }

    setClaimBusyHardwareId(hardwareId)
    setClaimErrorByHardwareId((current) => ({ ...current, [hardwareId]: '' }))
    try {
      await claimDevice(session.token, hardwareId, claimPassword)
      await loadDashboard(session.token, supervised)
    } catch (error) {
      setClaimErrorByHardwareId((current) => ({
        ...current,
        [hardwareId]: error instanceof Error ? error.message : 'Claim failed',
      }))
    } finally {
      setClaimBusyHardwareId(null)
    }
  }

  async function handleSupervise() {
    if (!session) {
      return
    }

    setSuperviseBusy(true)
    setPageError('')
    try {
      const inventoryData = inventory.length ? inventory : await fetchInventory(session.token)
      const claimedData = claimedDevices.length ? claimedDevices : await fetchClaimedDevices(session.token)
      const nitwData = nitwReference ?? (await fetchNitwReference(session.token))
      const comparisonIndex = await superviseNodes(session.token, inventoryData, claimedData, nitwData)
      setInventory(inventoryData)
      setClaimedDevices(claimedData)
      setNitwReference(nitwData)
      setCompareByElementId(comparisonIndex)
      setSupervised(true)
    } catch (error) {
      setPageError(error instanceof Error ? error.message : 'Supervision failed')
    } finally {
      setSuperviseBusy(false)
    }
  }

  async function handleSaveNode() {
    if (!session || !nitwReference || !draftNode) {
      return
    }

    setSaveNodeBusy(true)
    setSaveNodeError('')
    try {
      const { networkPayload, hardwareId } = buildNetworkWithDraftNode(nitwReference, draftNode)
      await syncNetwork(session.token, networkPayload)
      setAddNodeMode(false)
      setDraftNode(null)
      setSelectedHardwareId(hardwareId)
      await loadDashboard(session.token, supervised)
      setSelectedHardwareId(hardwareId)
    } catch (error) {
      setSaveNodeError(error instanceof Error ? error.message : 'Failed to add node')
    } finally {
      setSaveNodeBusy(false)
    }
  }

  function beginAddNodeMode() {
    setAddNodeMode(true)
    setSaveNodeError('')
    setDraftNode((current) => current ?? createInitialDraftNode())
  }

  function cancelAddNode() {
    setAddNodeMode(false)
    setDraftNode(null)
    setSaveNodeError('')
  }

  function markNodeReview(nodeId: string, decision: NodeReviewDecision) {
    setReviewByNodeId((current) => ({
      ...current,
      [nodeId]: decision,
    }))
  }

  function clearNodeReview(nodeId: string) {
    setReviewByNodeId((current) => {
      const next = { ...current }
      delete next[nodeId]
      return next
    })
  }

  function logout() {
    window.localStorage.removeItem(SESSION_KEY)
    setSession(null)
    setInventory([])
    setClaimedDevices([])
    setNitwReference(null)
    setCompareByElementId({})
    setSelectedHardwareId('')
    setSupervised(false)
  }

  if (!session) {
    return (
      <main className="auth-shell">
        <section className="auth-card">
          <p className="kicker">INNOTHON Access</p>
          <h1>{authMode === 'login' ? 'Login to claim grid nodes' : 'Create your operator account'}</h1>
          <p className="auth-copy">
            Staff users can sign in, inspect campus nodes, and claim the ones they manage.
          </p>
          <form className="auth-form" onSubmit={handleAuthSubmit}>
            <label>
              <span>Email</span>
              <input value={email} onChange={(event) => setEmail(event.target.value)} type="email" required />
            </label>
            <label>
              <span>Password</span>
              <input value={password} onChange={(event) => setPassword(event.target.value)} type="password" minLength={8} required />
            </label>
            {authError ? <div className="form-error">{authError}</div> : null}
            <button disabled={authBusy} type="submit">
              {authBusy ? 'Please wait...' : authMode === 'login' ? 'Login' : 'Register'}
            </button>
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
          <p className="kicker">NITW Network Control</p>
          <h1>Claim campus nodes and inspect model deviations</h1>
          <p className="header-copy">Signed in as {session.email}</p>
        </div>
        <div className="header-actions">
          <div className="header-stats">
            <div className="header-stat">
              <span>Claimed by you</span>
              <strong>{stats.claimed}</strong>
            </div>
            <div className="header-stat">
              <span>Blue nodes</span>
              <strong>{stats.blue}</strong>
            </div>
            <div className="header-stat">
              <span>Green nodes</span>
              <strong>{stats.green}</strong>
            </div>
            <div className="header-stat">
              <span>Red nodes</span>
              <strong>{stats.red}</strong>
            </div>
          </div>
          <div className="header-button-row">
            <button className="ghost-button" disabled={pageBusy || saveNodeBusy} onClick={beginAddNodeMode} type="button">
              Add node
            </button>
            <button className="ghost-button ghost-button--accent" disabled={pageBusy || superviseBusy} onClick={() => void handleSupervise()} type="button">
              {superviseBusy ? 'Supervising...' : 'Supervise'}
            </button>
            <button className="ghost-button" onClick={logout} type="button">
              Logout
            </button>
          </div>
        </div>
      </header>

      {pageError ? <section className="banner banner--error">{pageError}</section> : null}

      <section className="network-layout">
        <section className="map-card">
          <MapContainer center={CAMPUS_CENTER} className="network-map" zoom={17} zoomControl={false}>
            <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <ZoomControl position="bottomright" />
            <MapPlacementHandler
              active={addNodeMode}
              onPlace={(lat, lng) =>
                setDraftNode((current) => ({
                  ...(current ?? createInitialDraftNode()),
                  lat,
                  lng,
                }))
              }
            />

            {nodes.map((node) => (
              <Polyline
                key={`line-${node.hardwareId}`}
                pathOptions={{
                  color: edgeColor(node.status),
                  dashArray: '10 10',
                  weight: 4,
                }}
                positions={[PUMP_STATION, [node.lat, node.lng]]}
              />
            ))}

            <Marker icon={PUMP_ICON} position={PUMP_STATION}>
              <Popup>
                <div className="popup-card">
                  <strong>Main Feed</strong>
                  <span>Campus distribution source.</span>
                </div>
              </Popup>
            </Marker>

            {draftNode ? (
              <Marker
                draggable
                eventHandlers={{
                  dragend: (event) => {
                    const marker = event.target
                    const position = marker.getLatLng()
                    setDraftNode((current) =>
                      current
                        ? {
                            ...current,
                            lat: position.lat,
                            lng: position.lng,
                          }
                        : current,
                    )
                  },
                }}
                position={[draftNode.lat, draftNode.lng]}
              >
                <Popup>
                  <div className="popup-card">
                    <strong>{draftNode.name || 'New node'}</strong>
                    <span>Drag this marker to refine placement.</span>
                    <span>{draftNode.lat.toFixed(6)}, {draftNode.lng.toFixed(6)}</span>
                  </div>
                </Popup>
              </Marker>
            ) : null}

            {nodes.map((node) => (
              <CircleMarker
                center={[node.lat, node.lng]}
                eventHandlers={{ click: () => setSelectedHardwareId(node.hardwareId) }}
                key={node.hardwareId}
                pathOptions={{
                  color: borderColor(node.status),
                  fillColor: fillColor(node.status),
                  fillOpacity: 0.94,
                  weight: selectedHardwareId === node.hardwareId ? 4 : 2,
                }}
                radius={selectedHardwareId === node.hardwareId ? 11 : 9}
              >
                <Tooltip direction="top" offset={[0, -8]}>
                  {node.name}
                </Tooltip>
                <Popup>
                  <div className="popup-card popup-card--wide">
                    <strong>{node.name}</strong>
                    <span>{node.hardwareId}</span>
                    <span>Bus: {node.busId}</span>
                    <span>Expected load: {node.expectedMw.toFixed(2)} MW</span>
                    <span>Current load: {node.currentMw.toFixed(2)} MW</span>
                    <span>Model status: {comparisonLabel(node.comparisonStatus)}</span>
                    <span>Simulated exact: {node.comparedExpectedMw !== null ? formatMw(node.comparedExpectedMw) : 'Topology issue / unavailable'}</span>
                    <span>Measured exact: {node.comparedActualMw !== null ? formatMw(node.comparedActualMw) : 'No reading'}</span>
                    <span>Delta: {node.deltaMw !== null ? formatSignedMw(node.deltaMw) : 'Not comparable'}</span>
                    <span>Claims: {node.claimCount}</span>
                    <span className={`map-badge map-badge--${node.status}`}>
                      {statusLabel(node.status)}
                    </span>
                    {node.reviewDecision ? (
                      <span className="map-badge map-badge--review">
                        User review: {node.reviewDecision === 'normal' ? 'Marked normal' : 'Keep anomaly'}
                      </span>
                    ) : null}
                    {node.claimedByCurrentUser && supervised && node.comparisonStatus === 'deviation' ? (
                      <div className="review-box">
                        <strong>Review this anomaly</strong>
                        <div className="review-actions">
                          <button onClick={() => markNodeReview(node.id, 'normal')} type="button">
                            Mark normal
                          </button>
                          <button onClick={() => markNodeReview(node.id, 'anomaly')} type="button">
                            Keep anomaly
                          </button>
                          {node.reviewDecision ? (
                            <button className="ghost-button" onClick={() => clearNodeReview(node.id)} type="button">
                              Clear review
                            </button>
                          ) : null}
                        </div>
                      </div>
                    ) : null}
                    {!node.claimedByCurrentUser ? (
                      <div className="claim-box">
                        <label>
                          <span>Claim password</span>
                          <input
                            onChange={(event) =>
                              setClaimPasswords((current) => ({
                                ...current,
                                [node.hardwareId]: event.target.value,
                              }))
                            }
                            placeholder={node.claimPasswordHint}
                            type="password"
                            value={claimPasswords[node.hardwareId] ?? ''}
                          />
                        </label>
                        {claimErrorByHardwareId[node.hardwareId] ? (
                          <div className="form-error">{claimErrorByHardwareId[node.hardwareId]}</div>
                        ) : null}
                        <button
                          disabled={claimBusyHardwareId === node.hardwareId}
                          onClick={() => void handleClaim(node.hardwareId)}
                          type="button"
                        >
                          {claimBusyHardwareId === node.hardwareId ? 'Claiming...' : 'Claim node'}
                        </button>
                      </div>
                    ) : (
                      <div className="claim-success">
                        {supervised
                          ? 'Claimed by you. This node is now supervised by the model.'
                          : 'Claimed by you. Click Supervise to run deviation checks.'}
                      </div>
                    )}
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </section>

        <aside className="side-panel">
          {addNodeMode ? (
            <article className="panel panel--composer">
              <div className="panel-heading">
                <div>
                  <p className="kicker">Node Composer</p>
                  <h2>Add a campus node</h2>
                </div>
                <span className="status-badge status-unclaimed">Draft</span>
              </div>
              <p className="composer-copy">
                Click anywhere on the map, then drag the draft marker until the placement looks right.
              </p>
              <div className="composer-form">
                <label>
                  <span>Node name</span>
                  <input
                    onChange={(event) =>
                      setDraftNode((current) =>
                        current
                          ? {
                              ...current,
                              name: event.target.value,
                            }
                          : current,
                      )
                    }
                    placeholder="New academic block"
                    value={draftNode?.name ?? ''}
                  />
                </label>
                <label>
                  <span>Active load (MW)</span>
                  <input
                    min="0"
                    onChange={(event) =>
                      setDraftNode((current) =>
                        current
                          ? {
                              ...current,
                              pMw: event.target.value,
                            }
                          : current,
                      )
                    }
                    step="0.01"
                    type="number"
                    value={draftNode?.pMw ?? ''}
                  />
                </label>
                <label>
                  <span>Reactive load (MVAR)</span>
                  <input
                    min="0"
                    onChange={(event) =>
                      setDraftNode((current) =>
                        current
                          ? {
                              ...current,
                              qMvar: event.target.value,
                            }
                          : current,
                      )
                    }
                    step="0.01"
                    type="number"
                    value={draftNode?.qMvar ?? ''}
                  />
                </label>
                <label>
                  <span>Bus voltage (kV)</span>
                  <input
                    min="0"
                    onChange={(event) =>
                      setDraftNode((current) =>
                        current
                          ? {
                              ...current,
                              vnKv: event.target.value,
                            }
                          : current,
                      )
                    }
                    step="0.1"
                    type="number"
                    value={draftNode?.vnKv ?? ''}
                  />
                </label>
              </div>
              {draftNode ? (
                <div className="draft-coordinates">
                  Draft position: {draftNode.lat.toFixed(6)}, {draftNode.lng.toFixed(6)}
                </div>
              ) : null}
              {saveNodeError ? <div className="form-error">{saveNodeError}</div> : null}
              <div className="composer-actions">
                <button disabled={saveNodeBusy || !draftNode?.name.trim()} onClick={() => void handleSaveNode()} type="button">
                  {saveNodeBusy ? 'Saving node...' : 'Save node'}
                </button>
                <button className="ghost-button" onClick={cancelAddNode} type="button">
                  Cancel
                </button>
              </div>
            </article>
          ) : null}

          <article className="panel panel--summary">
            <div className="metric">
              <span>Total nodes</span>
              <strong>{nodes.length}</strong>
            </div>
            <div className="metric">
              <span>Status</span>
              <strong>{pageBusy ? 'Refreshing...' : supervised ? 'Supervised' : 'Ready to supervise'}</strong>
            </div>
            <div className="metric">
              <span>MQTT safety</span>
              <strong>Per-device token</strong>
            </div>
          </article>

          {selectedNode ? (
            <>
              <article className="panel">
                <div className="panel-heading">
                  <div>
                    <p className="kicker">Selected Node</p>
                    <h2>{selectedNode.name}</h2>
                  </div>
                  <span className={`status-badge status-${selectedNode.status}`}>
                    {statusLabel(selectedNode.status)}
                  </span>
                </div>
                {selectedNode.reviewDecision ? (
                  <div className="review-note">
                    User review: {selectedNode.reviewDecision === 'normal' ? 'Marked normal by operator' : 'Confirmed as anomaly by operator'}
                  </div>
                ) : null}

                <div className="detail-list">
                  <div><span>Hardware ID</span><strong>{selectedNode.hardwareId}</strong></div>
                  <div><span>Bus</span><strong>{selectedNode.busId}</strong></div>
                  <div><span>Expected</span><strong>{selectedNode.expectedMw.toFixed(2)} MW</strong></div>
                  <div><span>Current</span><strong>{selectedNode.currentMw.toFixed(2)} MW</strong></div>
                  <div><span>Model status</span><strong>{comparisonLabel(selectedNode.comparisonStatus)}</strong></div>
                  <div><span>Simulated exact</span><strong>{selectedNode.comparedExpectedMw !== null ? formatMw(selectedNode.comparedExpectedMw) : 'Topology issue / unavailable'}</strong></div>
                  <div><span>Measured exact</span><strong>{selectedNode.comparedActualMw !== null ? formatMw(selectedNode.comparedActualMw) : 'No reading'}</strong></div>
                  <div><span>Delta</span><strong>{selectedNode.deltaMw !== null ? formatSignedMw(selectedNode.deltaMw) : 'Not comparable'}</strong></div>
                  <div><span>Sensor</span><strong>{selectedNode.sensorId}</strong></div>
                  <div><span>Coordinates</span><strong>{selectedNode.lat.toFixed(6)}, {selectedNode.lng.toFixed(6)}</strong></div>
                </div>
                {selectedNode.claimedByCurrentUser && supervised && selectedNode.comparisonStatus === 'deviation' ? (
                  <div className="review-box review-box--panel">
                    <strong>Operator decision</strong>
                    <div className="review-actions">
                      <button onClick={() => markNodeReview(selectedNode.id, 'normal')} type="button">
                        Mark normal
                      </button>
                      <button onClick={() => markNodeReview(selectedNode.id, 'anomaly')} type="button">
                        Keep anomaly
                      </button>
                      {selectedNode.reviewDecision ? (
                        <button className="ghost-button" onClick={() => clearNodeReview(selectedNode.id)} type="button">
                          Clear review
                        </button>
                      ) : null}
                    </div>
                  </div>
                ) : null}
              </article>

              <article className="panel panel--list">
                <div className="panel-heading">
                  <div>
                    <p className="kicker">Legend</p>
                    <h2>Node colors</h2>
                  </div>
                </div>
                <div className="building-list">
                  <div className="building-row legend-row">
                    <div>
                      <strong>Blue</strong>
                      <span>Not claimed by this user yet</span>
                    </div>
                  </div>
                  <div className="building-row legend-row">
                    <div>
                      <strong>Green</strong>
                      <span>Claimed and no deviation after supervision</span>
                    </div>
                  </div>
                  <div className="building-row legend-row">
                    <div>
                      <strong>Red</strong>
                      <span>Claimed and deviating after supervision</span>
                    </div>
                  </div>
                </div>
              </article>
            </>
          ) : null}
        </aside>
      </section>
    </main>
  )
}

function MapPlacementHandler({
  active,
  onPlace,
}: {
  active: boolean
  onPlace: (lat: number, lng: number) => void
}) {
  useMapEvents({
    click(event) {
      if (!active) {
        return
      }
      onPlace(event.latlng.lat, event.latlng.lng)
    },
  })

  return null
}

async function superviseNodes(
  token: string,
  inventory: DeviceRecord[],
  claimedDevices: DeviceRecord[],
  nitwReference: NitwReference,
) {
  const readingsPayload = buildReadingsPayload(inventory, claimedDevices, nitwReference)
  
  const compare = await compareNitwNetwork(token, nitwReference, readingsPayload)
  console.log("dbg" , compare)
  return Object.fromEntries(
    (compare.comparisons ?? [])
      .filter((entry) => entry.element_type === 'load')
      .map((entry) => [entry.element_id, entry]),
  )
}

function buildReadingsPayload(
  inventory: DeviceRecord[],
  claimedDevices: DeviceRecord[],
  nitwReference: NitwReference,
): Record<string, number> {
  const claimedByHardwareId = new Map(claimedDevices.map((device) => [device.hardwareId, device]))
  const readings: Record<string, number> = {}

  for (const load of nitwReference.loads) {
    const hardwareId = hardwareIdForLoadId(load.id)
    const inventoryDevice = inventory.find((device) => device.hardwareId === hardwareId)
    const claimedDevice = claimedByHardwareId.get(hardwareId)
    const sensorId =
      nitwReference.sensor_links.find((link) => link.element_type === 'load' && link.element_id === load.id)?.sensor_id ??
      inventoryDevice?.sensorManifest[0]?.sensorId

    if (!sensorId) {
      continue
    }

    const latest = claimedDevice?.latestReadings[0]
    readings[sensorId] = typeof latest?.value === 'number' ? latest.value : fakeReadingForLoad(load)
  }

  return readings
}

function fakeReadingForLoad(load: NitwReference['loads'][number] | undefined) {
  if (!load) {
    return 0
  }
  const deviationFactor = load.id.length % 3 === 0 ? 1.18 : 1
  return Number((load.p_mw * deviationFactor).toFixed(3))
}

function fillColor(status: NodeVisualStatus) {
  if (status === 'healthy') return '#64d7a1'
  if (status === 'deviation') return '#f09090'
  return '#7eb6ff'
}

function borderColor(status: NodeVisualStatus) {
  if (status === 'healthy') return '#17885c'
  if (status === 'deviation') return '#c44747'
  return '#2e6bd3'
}

function edgeColor(status: NodeVisualStatus) {
  if (status === 'healthy') return '#1b9f6e'
  if (status === 'deviation') return '#d74b4b'
  return '#2c70d8'
}

function statusLabel(status: NodeVisualStatus) {
  if (status === 'healthy') return 'Healthy'
  if (status === 'deviation') return 'Deviation'
  return 'Unclaimed'
}

function createInitialDraftNode(): DraftNode {
  return {
    name: '',
    lat: 17.98369646253154,
    lng: 79.53082786635768,
    pMw: '0.30',
    qMvar: '0.10',
    vnKv: '20',
  }
}

function buildNetworkWithDraftNode(nitwReference: NitwReference, draftNode: DraftNode) {
  const name = draftNode.name.trim()
  if (!name) {
    throw new Error('Node name is required')
  }

  const loadId = buildUniqueId(
    `load_${slugify(name)}`,
    nitwReference.loads.map((load) => load.id),
  )
  const busId = buildUniqueId(
    `bus_${slugify(name)}`,
    nitwReference.buses.map((bus) => bus.id),
  )
  const sensorId = buildUniqueId(
    `sensor_${loadId}`,
    nitwReference.sensor_links.map((link) => link.sensor_id),
  )
  const pMw = Number(draftNode.pMw)
  const qMvar = Number(draftNode.qMvar)
  const vnKv = Number(draftNode.vnKv)

  if (!Number.isFinite(pMw) || pMw < 0) {
    throw new Error('Active load must be a valid non-negative number')
  }
  if (!Number.isFinite(qMvar) || qMvar < 0) {
    throw new Error('Reactive load must be a valid non-negative number')
  }
  if (!Number.isFinite(vnKv) || vnKv <= 0) {
    throw new Error('Bus voltage must be a valid positive number')
  }

  return {
    hardwareId: `NODE-${loadId.replaceAll('_', '-').toUpperCase()}`,
    networkPayload: {
      ...nitwReference,
      buses: [
        ...nitwReference.buses,
        {
          id: busId,
          name: `Bus ${name}`,
          vn_kv: vnKv,
          type: 'b',
        },
      ],
      loads: [
        ...nitwReference.loads,
        {
          id: loadId,
          name,
          bus_id: busId,
          p_mw: pMw,
          q_mvar: qMvar,
          lat: draftNode.lat,
          long: draftNode.lng,
        },
      ],
      sensor_links: [
        ...nitwReference.sensor_links,
        {
          sensor_id: sensorId,
          element_type: 'load',
          element_id: loadId,
          measurement: 'p_mw',
        },
      ],
    },
  }
}

function slugify(value: string) {
  return value
    .toLowerCase()
    .trim()
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

function buildUniqueId(baseId: string, existingIds: string[]) {
  if (!existingIds.includes(baseId)) {
    return baseId
  }

  let counter = 2
  while (existingIds.includes(`${baseId}_${counter}`)) {
    counter += 1
  }
  return `${baseId}_${counter}`
}

function hardwareIdForLoadId(loadId: string | undefined) {
  if (!loadId) {
    return ''
  }
  return `NODE-${loadId.replaceAll('_', '-').toUpperCase()}`
}

function formatMw(value: number) {
  return `${value.toFixed(4)} MW`
}

function formatSignedMw(value: number) {
  const sign = value > 0 ? '+' : ''
  return `${sign}${value.toFixed(4)} MW`
}

function comparisonLabel(status: string | null) {
  if (!status) {
    return 'Not run yet'
  }
  if (status === 'topology_issue') {
    return 'Topology issue'
  }
  if (status === 'missing_actual') {
    return 'Missing sensor value'
  }
  if (status === 'missing_expected') {
    return 'Missing simulation value'
  }
  if (status === 'match') {
    return 'Match'
  }
  if (status === 'deviation') {
    return 'Deviation'
  }
  return status
}

export default App
