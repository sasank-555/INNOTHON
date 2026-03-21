import { useMemo, useState } from 'react'
import { CircleMarker, MapContainer, Marker, Popup, Polyline, TileLayer, Tooltip, ZoomControl } from 'react-leaflet'
import { divIcon } from 'leaflet'
import type { LatLngExpression } from 'leaflet'

import './App.css'

type Status = 'normal' | 'suspicious' | 'anomaly'

type BuildingNode = {
  id: string
  name: string
  busId: string
  pMw: number
  qMvar: number
  lat: number
  lng: number
  sensorId: string
  measurement: string
  status: Status
}

const CAMPUS_CENTER: LatLngExpression = [17.98369646253154, 79.53082786635768]
const PUMP_STATION: LatLngExpression = [17.98369646253154, 79.53082786635768]
const PUMP_ICON = divIcon({
  className: 'pump-marker',
  html: '<div class="pump-marker__inner"><strong>Pump Station</strong><span>Source Node</span></div>',
})

function statusFromLoad(pMw: number): Status {
  if (pMw >= 0.58) {
    return 'anomaly'
  }
  if (pMw >= 0.42) {
    return 'suspicious'
  }
  return 'normal'
}

const BUILDINGS: BuildingNode[] = [
  { id: 'load_chem_dept', name: 'CHEM DEPT', busId: 'bus_b1', pMw: 0.5, qMvar: 0.2, lat: 17.985566361807546, lng: 79.53388386718099, sensorId: 'sensor_load_chem_dept', measurement: 'p_mw', status: statusFromLoad(0.5) },
  { id: 'load_lh', name: 'LH', busId: 'bus_b2', pMw: 0.4, qMvar: 0.15, lat: 17.985765350695704, lng: 79.53161471839925, sensorId: 'sensor_load_lh', measurement: 'p_mw', status: statusFromLoad(0.4) },
  { id: 'load_siemens', name: 'Siemens Centre of Excellence', busId: 'bus_b3', pMw: 0.6, qMvar: 0.25, lat: 17.982723791958378, lng: 79.53290875258377, sensorId: 'sensor_load_siemens', measurement: 'p_mw', status: statusFromLoad(0.6) },
  { id: 'load_ped', name: 'PED', busId: 'bus_b4', pMw: 0.45, qMvar: 0.18, lat: 17.9817090323481, lng: 79.53247172855703, sensorId: 'sensor_load_ped', measurement: 'p_mw', status: statusFromLoad(0.45) },
  { id: 'load_dispensary', name: 'DISPENSARY', busId: 'bus_b5', pMw: 0.3, qMvar: 0.1, lat: 17.981158442071962, lng: 79.52957737723754, sensorId: 'sensor_load_dispensary', measurement: 'p_mw', status: statusFromLoad(0.3) },
  { id: 'load_ifc_a', name: 'IFC A', busId: 'bus_b6', pMw: 0.5, qMvar: 0.2, lat: 17.983706566261628, lng: 79.53435269736654, sensorId: 'sensor_load_ifc_a', measurement: 'p_mw', status: statusFromLoad(0.5) },
  { id: 'load_mme', name: 'MME', busId: 'bus_b7', pMw: 0.55, qMvar: 0.22, lat: 17.984682554681754, lng: 79.53394928246638, sensorId: 'sensor_load_mme', measurement: 'p_mw', status: statusFromLoad(0.55) },
  { id: 'load_mfc', name: 'mFC', busId: 'bus_b8', pMw: 0.35, qMvar: 0.12, lat: 17.984252512451206, lng: 79.53265697091757, sensorId: 'sensor_load_mfc', measurement: 'p_mw', status: statusFromLoad(0.35) },
  { id: 'load_ccpd', name: 'CCPD', busId: 'bus_b9', pMw: 0.4, qMvar: 0.15, lat: 17.984021500243745, lng: 79.53334288220447, sensorId: 'sensor_load_ccpd', measurement: 'p_mw', status: statusFromLoad(0.4) },
  { id: 'load_lib', name: 'LIB', busId: 'bus_b10', pMw: 0.6, qMvar: 0.25, lat: 17.98445825915247, lng: 79.53009085887841, sensorId: 'sensor_load_lib', measurement: 'p_mw', status: statusFromLoad(0.6) },
  { id: 'load_alc', name: 'ALC', busId: 'bus_b11', pMw: 0.3, qMvar: 0.1, lat: 17.98466149435941, lng: 79.5292788921786, sensorId: 'sensor_load_alc', measurement: 'p_mw', status: statusFromLoad(0.3) },
  { id: 'load_nescafe', name: 'NESCAFE', busId: 'bus_b12', pMw: 0.25, qMvar: 0.08, lat: 17.98423626350315, lng: 79.52976212740914, sensorId: 'sensor_load_nescafe', measurement: 'p_mw', status: statusFromLoad(0.25) },
  { id: 'load_taaza', name: 'TAAZA', busId: 'bus_b13', pMw: 0.2, qMvar: 0.07, lat: 17.981668404452318, lng: 79.52942723582078, sensorId: 'sensor_load_taaza', measurement: 'p_mw', status: statusFromLoad(0.2) },
  { id: 'load_hostel_life', name: 'HOSTEL LIFE', busId: 'bus_b14', pMw: 0.7, qMvar: 0.3, lat: 17.98001778283484, lng: 79.53024696203269, sensorId: 'sensor_load_hostel_life', measurement: 'p_mw', status: statusFromLoad(0.7) },
]

const STATUS_LABELS: Record<Status, string> = {
  normal: 'Normal',
  suspicious: 'Suspicious',
  anomaly: 'Anomaly',
}

function statusClass(status: Status) {
  return `status-${status}`
}

function App() {
  const [selectedId, setSelectedId] = useState(BUILDINGS[0]?.id ?? '')

  const selectedBuilding = BUILDINGS.find((building) => building.id === selectedId) ?? BUILDINGS[0]

  const stats = useMemo(
    () => ({
      nodeCount: BUILDINGS.length + 1,
      totalDemandMw: BUILDINGS.reduce((sum, building) => sum + building.pMw, 0),
      suspicious: BUILDINGS.filter((building) => building.status === 'suspicious').length,
      anomalies: BUILDINGS.filter((building) => building.status === 'anomaly').length,
    }),
    [],
  )

  return (
    <main className="network-shell">
      <header className="network-header">
        <div>
          <p className="kicker">NITW Network Map</p>
          <h1>Buildings as nodes, pump station as source</h1>
        </div>

        <div className="header-stats">
          <div className="header-stat">
            <span>Nodes</span>
            <strong>{stats.nodeCount}</strong>
          </div>
          <div className="header-stat">
            <span>Total Demand</span>
            <strong>{stats.totalDemandMw.toFixed(2)} MW</strong>
          </div>
        </div>
      </header>

      <section className="network-layout">
        <section className="map-card">
          <MapContainer center={CAMPUS_CENTER} className="network-map" zoom={17} zoomControl={false}>
            <TileLayer attribution='&copy; OpenStreetMap contributors' url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
            <ZoomControl position="bottomright" />

            {BUILDINGS.map((building) => (
              <Polyline
                key={`line-${building.id}`}
                pathOptions={{
                  color:
                    building.status === 'anomaly'
                      ? '#d74b4b'
                      : building.status === 'suspicious'
                        ? '#d39b1b'
                        : '#149777',
                  dashArray: '10 10',
                  weight: 4,
                }}
                positions={[PUMP_STATION, [building.lat, building.lng]]}
              />
            ))}

            <Marker icon={PUMP_ICON} position={PUMP_STATION}>
              <Popup>
                <div className="popup-card">
                  <strong>Pump Station</strong>
                  <span>Main source node for the displayed network.</span>
                </div>
              </Popup>
            </Marker>

            {BUILDINGS.map((building) => (
              <CircleMarker
                center={[building.lat, building.lng]}
                eventHandlers={{ click: () => setSelectedId(building.id) }}
                key={building.id}
                pathOptions={{
                  color:
                    building.status === 'anomaly'
                      ? '#c53e3e'
                      : building.status === 'suspicious'
                        ? '#b78611'
                        : '#127d69',
                  fillColor:
                    building.status === 'anomaly'
                      ? '#ef8d8d'
                      : building.status === 'suspicious'
                        ? '#f1cf68'
                        : '#68d7be',
                  fillOpacity: 0.94,
                  weight: selectedId === building.id ? 4 : 2,
                }}
                radius={selectedId === building.id ? 11 : 9}
              >
                <Tooltip direction="top" offset={[0, -8]}>{building.name}</Tooltip>
                <Popup>
                  <div className="popup-card">
                    <strong>{building.name}</strong>
                    <span>Bus: {building.busId}</span>
                    <span>P: {building.pMw} MW</span>
                    <span>Q: {building.qMvar} MVAR</span>
                    <span>Sensor: {building.sensorId}</span>
                    <span>Lat: {building.lat.toFixed(6)}</span>
                    <span>Lng: {building.lng.toFixed(6)}</span>
                  </div>
                </Popup>
              </CircleMarker>
            ))}
          </MapContainer>
        </section>

        <aside className="side-panel">
          <article className="panel panel--summary">
            <div className="metric">
              <span>Suspicious</span>
              <strong>{stats.suspicious}</strong>
            </div>
            <div className="metric">
              <span>Anomalies</span>
              <strong>{stats.anomalies}</strong>
            </div>
            <div className="metric">
              <span>Source</span>
              <strong>Pump Station</strong>
            </div>
          </article>

          <article className="panel">
            <div className="panel-heading">
              <div>
                <p className="kicker">Selected Building</p>
                <h2>{selectedBuilding.name}</h2>
              </div>
              <span className={`status-badge ${statusClass(selectedBuilding.status)}`}>
                {STATUS_LABELS[selectedBuilding.status]}
              </span>
            </div>

            <div className="detail-list">
              <div><span>Bus</span><strong>{selectedBuilding.busId}</strong></div>
              <div><span>Active Power</span><strong>{selectedBuilding.pMw} MW</strong></div>
              <div><span>Reactive Power</span><strong>{selectedBuilding.qMvar} MVAR</strong></div>
              <div><span>Sensor</span><strong>{selectedBuilding.sensorId}</strong></div>
              <div><span>Measurement</span><strong>{selectedBuilding.measurement}</strong></div>
              <div><span>Coordinates</span><strong>{selectedBuilding.lat.toFixed(6)}, {selectedBuilding.lng.toFixed(6)}</strong></div>
              <div><span>Connection</span><strong>Pump Station</strong></div>
            </div>
          </article>

          <article className="panel panel--list">
            <div className="panel-heading">
              <div>
                <p className="kicker">Buildings</p>
                <h2>Network nodes</h2>
              </div>
            </div>

            <div className="building-list">
              {BUILDINGS.map((building) => (
                <button
                  className={`building-row ${building.id === selectedBuilding.id ? 'is-selected' : ''}`}
                  key={building.id}
                  onClick={() => setSelectedId(building.id)}
                  type="button"
                >
                  <div>
                    <strong>{building.name}</strong>
                    <span>{building.busId}</span>
                  </div>
                  <span className={`mini-badge ${statusClass(building.status)}`}>
                    {STATUS_LABELS[building.status]}
                  </span>
                </button>
              ))}
            </div>
          </article>
        </aside>
      </section>
    </main>
  )
}

export default App
