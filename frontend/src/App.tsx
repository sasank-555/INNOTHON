import { useEffect, useMemo, useState } from 'react'
import { MapContainer, TileLayer, ZoomControl, useMap } from 'react-leaflet'
import type { LatLngExpression } from 'leaflet'

import './App.css'

type Status = 'normal' | 'suspicious' | 'anomaly'

type FloorState = {
  id: string
  label: string
  loadKw: number
  status: Status
}

type BuildingState = {
  id: string
  label: string
  lat: number
  lng: number
  baseLoadKw: number
  loadKw: number
  status: Status
  floors: FloorState[]
}

const CAMPUS_CENTER: LatLngExpression = [17.98369646253154, 79.53082786635768]
const SOURCE = {
  id: 'station',
  label: 'Power Station',
  lat: 17.98369646253154,
  lng: 79.53082786635768,
}

const STATUS_LABELS: Record<Status, string> = {
  normal: 'Normal',
  suspicious: 'Suspicious',
  anomaly: 'Anomaly',
}

function metersToLatLng(eastMeters: number, northMeters: number) {
  const [lat, lng] = CAMPUS_CENTER as [number, number]
  const latitude = lat + northMeters / 111_320
  const longitude = lng + eastMeters / (111_320 * Math.cos((lat * Math.PI) / 180))
  return { lat: latitude, lng: longitude }
}

function seedBuildings(): BuildingState[] {
  const templates = [
    { id: 'eng', label: 'Engineering Block', offset: [92, 46], baseLoadKw: 226 },
    { id: 'admin', label: 'Admin Block', offset: [-74, 54], baseLoadKw: 142 },
    { id: 'library', label: 'Central Library', offset: [128, -32], baseLoadKw: 174 },
    { id: 'labs', label: 'Research Labs', offset: [-118, -46], baseLoadKw: 208 },
    { id: 'hostel', label: 'Hostel Complex', offset: [34, -118], baseLoadKw: 192 },
  ] as const

  return templates.map((building, index) => {
    const position = metersToLatLng(building.offset[0], building.offset[1])
    const floors = Array.from({ length: 4 }, (_, floorIndex) => {
      const load = Math.round(building.baseLoadKw / 4 + floorIndex * 3 + index * 2)
      return {
        id: `${building.id}-f${floorIndex + 1}`,
        label: `Floor ${floorIndex + 1}`,
        loadKw: load,
        status: 'normal' as Status,
      }
    })

    return {
      id: building.id,
      label: building.label,
      lat: position.lat,
      lng: position.lng,
      baseLoadKw: building.baseLoadKw,
      loadKw: floors.reduce((sum, floor) => sum + floor.loadKw, 0),
      status: 'normal',
      floors,
    }
  })
}

function computeStatus(loadKw: number, baselineKw: number): Status {
  const ratio = loadKw / baselineKw
  if (ratio > 1.18 || ratio < 0.76) {
    return 'anomaly'
  }
  if (ratio > 1.08 || ratio < 0.88) {
    return 'suspicious'
  }
  return 'normal'
}

function statusClass(status: Status) {
  return `status-${status}`
}

function CampusOverlay({
  buildings,
  selectedId,
  onSelect,
}: {
  buildings: BuildingState[]
  selectedId: string
  onSelect: (id: string) => void
}) {
  const map = useMap()
  const [, forceFrame] = useState(0)

  useEffect(() => {
    const update = () => forceFrame((value) => value + 1)
    map.on('zoom move resize', update)
    return () => {
      map.off('zoom move resize', update)
    }
  }, [map])

  const size = map.getSize()
  const sourcePoint = map.latLngToContainerPoint([SOURCE.lat, SOURCE.lng])

  return (
    <div className="campus-overlay">
      <svg className="campus-overlay__svg" height={size.y} width={size.x}>
        <defs>
          <marker
            id="energy-arrow"
            markerHeight="10"
            markerWidth="10"
            orient="auto-start-reverse"
            refX="9"
            refY="5"
          >
            <path d="M 0 0 L 10 5 L 0 10 z" fill="#0a7664" />
          </marker>
        </defs>

        {buildings.map((building) => {
          const targetPoint = map.latLngToContainerPoint([building.lat, building.lng])
          return (
            <line
              className={`energy-line ${statusClass(building.status)}`}
              key={`line-${building.id}`}
              markerEnd="url(#energy-arrow)"
              x1={sourcePoint.x}
              x2={targetPoint.x}
              y1={sourcePoint.y}
              y2={targetPoint.y}
            />
          )
        })}
      </svg>

      <button
        className="campus-node campus-node--station"
        style={{ left: sourcePoint.x, top: sourcePoint.y }}
        type="button"
      >
        <span>{SOURCE.label}</span>
      </button>

      {buildings.map((building) => {
        const point = map.latLngToContainerPoint([building.lat, building.lng])
        return (
          <button
            className={`campus-node ${statusClass(building.status)} ${selectedId === building.id ? 'is-selected' : ''}`}
            key={building.id}
            onClick={() => onSelect(building.id)}
            style={{ left: point.x, top: point.y }}
            type="button"
          >
            <strong>{building.label}</strong>
            <span>{building.loadKw} kW</span>
          </button>
        )
      })}
    </div>
  )
}

function App() {
  const [buildings, setBuildings] = useState<BuildingState[]>(() => seedBuildings())
  const [selectedBuildingId, setSelectedBuildingId] = useState('eng')
  const [lastUpdated, setLastUpdated] = useState(new Date())

  useEffect(() => {
    const intervalId = window.setInterval(() => {
      setBuildings((current) =>
        current.map((building) => {
          const floors = building.floors.map((floor) => {
            const swing = (Math.random() - 0.5) * 12
            const anomalyBoost = Math.random() > 0.93 ? 24 : 0
            const nextLoad = Math.max(14, Math.round(floor.loadKw + swing + anomalyBoost))
            return {
              ...floor,
              loadKw: nextLoad,
              status: computeStatus(nextLoad, building.baseLoadKw / building.floors.length),
            }
          })

          const loadKw = floors.reduce((sum, floor) => sum + floor.loadKw, 0)
          return {
            ...building,
            floors,
            loadKw,
            status: computeStatus(loadKw, building.baseLoadKw),
          }
        }),
      )
      setLastUpdated(new Date())
    }, 2200)

    return () => window.clearInterval(intervalId)
  }, [])

  const selectedBuilding =
    buildings.find((building) => building.id === selectedBuildingId) ?? buildings[0]

  const stats = useMemo(() => {
    const anomalyCount = buildings.filter((building) => building.status === 'anomaly').length
    const suspiciousCount = buildings.filter((building) => building.status === 'suspicious').length
    const liveDemandKw = buildings.reduce((sum, building) => sum + building.loadKw, 0)
    return { anomalyCount, suspiciousCount, liveDemandKw }
  }, [buildings])

  const alerts = useMemo(
    () =>
      buildings
        .filter((building) => building.status !== 'normal')
        .sort((left, right) => right.loadKw - left.loadKw)
        .slice(0, 4),
    [buildings],
  )

  return (
    <main className="campus-shell">
      <header className="campus-header">
        <div>
          <p className="kicker">Campus Power Twin</p>
          <h1>Live campus energy map</h1>
        </div>
        <div className="live-pill">Updated {lastUpdated.toLocaleTimeString()}</div>
      </header>

      <section className="campus-layout">
        <section className="map-card">
          <div className="map-card__top">
            <div className="legend">
              <span><i className="legend-dot status-normal" /> Normal</span>
              <span><i className="legend-dot status-suspicious" /> Suspicious</span>
              <span><i className="legend-dot status-anomaly" /> Anomaly</span>
            </div>
          </div>

          <MapContainer
            center={CAMPUS_CENTER}
            className="campus-map"
            zoom={18}
            zoomControl={false}
          >
            <TileLayer
              attribution='&copy; OpenStreetMap contributors'
              url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
            />
            <ZoomControl position="bottomright" />
            <CampusOverlay
              buildings={buildings}
              selectedId={selectedBuilding.id}
              onSelect={setSelectedBuildingId}
            />
          </MapContainer>
        </section>

        <aside className="side-panel">
          <article className="panel panel--stats">
            <div className="stat">
              <span>Live Demand</span>
              <strong>{stats.liveDemandKw} kW</strong>
            </div>
            <div className="stat">
              <span>Suspicious</span>
              <strong>{stats.suspiciousCount}</strong>
            </div>
            <div className="stat">
              <span>Anomalies</span>
              <strong>{stats.anomalyCount}</strong>
            </div>
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="kicker">Building</p>
                <h2>{selectedBuilding.label}</h2>
              </div>
              <span className={`status-badge ${statusClass(selectedBuilding.status)}`}>
                {STATUS_LABELS[selectedBuilding.status]}
              </span>
            </div>

            <div className="building-meta">
              <span>{selectedBuilding.loadKw} kW live</span>
              <span>{selectedBuilding.floors.length} floors</span>
            </div>

            <div className="floor-list">
              {selectedBuilding.floors.map((floor) => (
                <div className="floor-row" key={floor.id}>
                  <div>
                    <strong>{floor.label}</strong>
                    <span>{floor.loadKw} kW</span>
                  </div>
                  <span className={`floor-status ${statusClass(floor.status)}`}>
                    {STATUS_LABELS[floor.status]}
                  </span>
                </div>
              ))}
            </div>
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="kicker">Alerts</p>
                <h2>Live issues</h2>
              </div>
            </div>

            <div className="alert-list">
              {alerts.length > 0 ? (
                alerts.map((building) => (
                  <button
                    className={`alert-card ${statusClass(building.status)}`}
                    key={building.id}
                    onClick={() => setSelectedBuildingId(building.id)}
                    type="button"
                  >
                    <strong>{building.label}</strong>
                    <span>{STATUS_LABELS[building.status]}</span>
                  </button>
                ))
              ) : (
                <div className="empty-state">No active building alerts.</div>
              )}
            </div>
          </article>
        </aside>
      </section>
    </main>
  )
}

export default App
