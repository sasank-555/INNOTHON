import {
  Background,
  BackgroundVariant,
  ConnectionMode,
  Controls,
  MiniMap,
  ReactFlow,
  ReactFlowProvider,
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  useReactFlow,
  type Connection,
  type Edge,
  type EdgeChange,
  type NodeChange,
  type NodeTypes,
} from '@xyflow/react'
import '@xyflow/react/dist/style.css'
import {
  type DragEvent,
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
} from 'react'

import './App.css'
import { PowerNode } from './PowerNode'
import {
  fetchFrontendGraphState,
  flowToServiceSnapshot,
  snapshotToFlow,
  updateServiceGraph,
} from './serviceX'
import type {
  FrontendGraphState,
  PowerFlowNode,
  PowerNodeData,
  PowerNodeKind,
  ProblemNode,
  SensorReadingRecord,
  Severity,
} from './types'

const NODE_TEMPLATES: Array<{
  kind: PowerNodeKind
  label: string
  nominalPowerKw: number
}> = [
  { kind: 'source', label: 'Grid Source', nominalPowerKw: 120 },
  { kind: 'battery', label: 'Battery Bank', nominalPowerKw: 35 },
  { kind: 'transformer', label: 'Transformer', nominalPowerKw: 88 },
  { kind: 'transmission', label: 'Transmission', nominalPowerKw: 54 },
  { kind: 'sink', label: 'Industrial Sink', nominalPowerKw: 96 },
]

const nodeTypes: NodeTypes = {
  powerNode: PowerNode,
}

function FlowEditor() {
  const wrapperRef = useRef<HTMLDivElement | null>(null)
  const nextIdRef = useRef(10)
  const hasHydratedRef = useRef(false)
  const lastSyncedGraphRef = useRef('')
  const { screenToFlowPosition, fitView } = useReactFlow()

  const [networkId, setNetworkId] = useState('network-alpha')
  const [networkName, setNetworkName] = useState('Loading...')
  const [nodes, setNodes] = useState<PowerFlowNode[]>([])
  const [edges, setEdges] = useState<Edge[]>([])
  const [sensorReadings, setSensorReadings] = useState<SensorReadingRecord[]>([])
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null)
  const [analysis, setAnalysis] = useState<FrontendGraphState['analysis'] | null>(null)
  const [isSyncingService, setIsSyncingService] = useState(false)
  const [isEditingGraph, setIsEditingGraph] = useState(false)
  const [hasUnsavedChanges, setHasUnsavedChanges] = useState(false)
  const [dismissedProblems, setDismissedProblems] = useState<Set<string>>(new Set())

  const currentSnapshot = useMemo(
    () => flowToServiceSnapshot(networkId, networkName, nodes, edges, sensorReadings),
    [edges, networkId, networkName, nodes, sensorReadings],
  )

  const decoratedNodes = useMemo(
    () =>
      nodes.map((node) => {
        const result = analysis?.nodes[node.id]
        return {
          ...node,
          data: {
            ...node.data,
            severity: result?.severity ?? node.data.severity,
            message:
              result?.message && typeof result.estimatedPowerKw === 'number'
                ? `${result.message} | ${Math.round(result.estimatedPowerKw)} kW est.`
                : node.data.message,
          },
        }
      }),
    [analysis, nodes],
  )

  const selectedNode = useMemo(
    () => nodes.find((node) => node.id === selectedNodeId) ?? null,
    [nodes, selectedNodeId],
  )

  const selectedSensorReading = useMemo(
    () => sensorReadings.find((reading) => reading.nodeId === selectedNodeId) ?? null,
    [selectedNodeId, sensorReadings],
  )

  const selectedNodeSeverity =
    selectedNode && analysis?.nodes[selectedNode.id]
      ? analysis.nodes[selectedNode.id].severity
      : selectedNode?.data.severity

  const visibleProblems = useMemo(() => {
    if (!analysis) {
      return []
    }
    return analysis.problems.filter((problem) => !dismissedProblems.has(problem.id))
  }, [analysis, dismissedProblems])

  const applyServiceState = useCallback((state: FrontendGraphState) => {
    const flow = snapshotToFlow(state.snapshot)
    lastSyncedGraphRef.current = JSON.stringify(state.snapshot.graph)
    setNetworkId(state.snapshot.network.id)
    setNetworkName(state.snapshot.network.name)
    setNodes(flow.nodes)
    setEdges(flow.edges)
    setSensorReadings(flow.sensorReadings)
    setAnalysis(state.analysis)
    setHasUnsavedChanges(false)
    setSelectedNodeId((currentSelectedNodeId) => {
      if (currentSelectedNodeId && flow.nodes.some((node) => node.id === currentSelectedNodeId)) {
        return currentSelectedNodeId
      }
      return flow.nodes[0]?.id ?? null
    })
  }, [])

  useEffect(() => {
    void fetchFrontendGraphState().then((state) => {
      applyServiceState(state)
      hasHydratedRef.current = true
      window.setTimeout(() => {
        fitView({ padding: 0.18 })
      }, 50)
    })
  }, [applyServiceState, fitView])

  const onNodesChange = useCallback((changes: NodeChange<PowerFlowNode>[]) => {
    if (
      isEditingGraph &&
      changes.some((change) => change.type !== 'select' && change.type !== 'dimensions')
    ) {
      setHasUnsavedChanges(true)
    }
    setNodes((currentNodes) => applyNodeChanges(changes, currentNodes))
  }, [isEditingGraph])

  const onEdgesChange = useCallback((changes: EdgeChange<Edge>[]) => {
    setEdges((currentEdges) => applyEdgeChanges(changes, currentEdges))
  }, [])

  const onConnect = useCallback((connection: Connection) => {
    if (!isEditingGraph) {
      return
    }
    setDismissedProblems(new Set())
    setHasUnsavedChanges(true)
    setEdges((currentEdges) =>
      addEdge(
        {
          ...connection,
          id: `edge-${connection.source}-${connection.target}-${Date.now()}`,
          animated: true,
        },
        currentEdges,
      ),
    )
  }, [isEditingGraph])

  const addNodeFromTemplate = useCallback(
    (kind: PowerNodeKind, position?: { x: number; y: number }) => {
      if (!isEditingGraph) {
        return
      }
      const node = createNode(kind, position ?? { x: 240, y: 220 }, nextIdRef.current++)
      setDismissedProblems(new Set())
      setHasUnsavedChanges(true)
      setNodes((currentNodes) => [...currentNodes, node])
      setSelectedNodeId(node.id)
    },
    [isEditingGraph],
  )

  const onDragStart = useCallback((event: DragEvent<HTMLButtonElement>, kind: PowerNodeKind) => {
    event.dataTransfer.setData('application/x-innothon-node', kind)
    event.dataTransfer.effectAllowed = 'move'
  }, [])

  const onDragOver = useCallback((event: DragEvent<HTMLDivElement>) => {
    if (!isEditingGraph) {
      return
    }
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
  }, [isEditingGraph])

  const onDrop = useCallback(
    (event: DragEvent<HTMLDivElement>) => {
      if (!isEditingGraph) {
        return
      }
      event.preventDefault()
      const kind = event.dataTransfer.getData('application/x-innothon-node') as PowerNodeKind
      if (!kind || !wrapperRef.current) {
        return
      }
      const position = screenToFlowPosition({
        x: event.clientX,
        y: event.clientY,
      })
      addNodeFromTemplate(kind, position)
    },
    [addNodeFromTemplate, isEditingGraph, screenToFlowPosition],
  )

  const updateSelectedNode = useCallback(
    (patch: Partial<PowerNodeData>) => {
      if (!selectedNodeId || !isEditingGraph) {
        return
      }
      setDismissedProblems(new Set())
      setHasUnsavedChanges(true)
      setNodes((currentNodes) =>
        currentNodes.map((node) =>
          node.id === selectedNodeId
            ? {
                ...node,
                data: {
                  ...node.data,
                  ...patch,
                },
              }
            : node,
        ),
      )
    },
    [isEditingGraph, selectedNodeId],
  )

  const removeSelectedNode = useCallback(() => {
    if (!selectedNodeId || !isEditingGraph) {
      return
    }
    setHasUnsavedChanges(true)
    setNodes((currentNodes) => currentNodes.filter((node) => node.id !== selectedNodeId))
    setEdges((currentEdges) =>
      currentEdges.filter(
        (edge) => edge.source !== selectedNodeId && edge.target !== selectedNodeId,
      ),
    )
    setSensorReadings((currentReadings) =>
      currentReadings.filter((reading) => reading.nodeId !== selectedNodeId),
    )
    setDismissedProblems((current) => {
      const next = new Set(current)
      next.delete(selectedNodeId)
      return next
    })
    setSelectedNodeId(null)
  }, [isEditingGraph, selectedNodeId])

  const handleTurnOff = useCallback((problem: ProblemNode) => {
    if (!isEditingGraph) {
      return
    }
    setDismissedProblems((current) => {
      const next = new Set(current)
      next.add(problem.id)
      return next
    })
    setHasUnsavedChanges(true)
    setNodes((currentNodes) =>
      currentNodes.map((node) =>
        node.id === problem.id
          ? {
              ...node,
              data: {
                ...node.data,
                active: false,
                severity: 'off',
                message: 'Turned off by operator',
              },
            }
          : node,
      ),
    )
  }, [isEditingGraph])

  const handleKeepAlive = useCallback((problem: ProblemNode) => {
    setDismissedProblems((current) => {
      const next = new Set(current)
      next.add(problem.id)
      return next
    })
  }, [])

  const saveGraph = useCallback(() => {
    if (!hasUnsavedChanges || isSyncingService) {
      return
    }

    setIsSyncingService(true)
    void updateServiceGraph(networkId, currentSnapshot.graph)
      .then((state) => {
        applyServiceState(state)
        setIsEditingGraph(false)
      })
      .finally(() => {
        setIsSyncingService(false)
      })
  }, [applyServiceState, currentSnapshot.graph, hasUnsavedChanges, isSyncingService, networkId])

  return (
    <div className="app-shell">
      <aside className="sidebar sidebar--left">
        <div className="sidebar__section">
          <p className="eyebrow">Service-driven</p>
          <h1 className="title">{networkName}</h1>
          <p className="lede">
            Service X provides the graph and sensor readings. This editor renders the
            network, runs the model, and only sends graph updates after the user saves.
          </p>
        </div>

        <div className="sidebar__section">
          <div className="section-title">Components</div>
          <div className="palette">
            {NODE_TEMPLATES.map((template) => (
              <button
                key={template.kind}
                className="palette__item"
                disabled={!isEditingGraph}
                draggable
                onDragStart={(event) => onDragStart(event, template.kind)}
                onClick={() => addNodeFromTemplate(template.kind)}
              >
                <span className={`swatch swatch--${template.kind}`} />
                <span>
                  {template.label}
                  <small>{template.nominalPowerKw} kW default</small>
                </span>
              </button>
            ))}
          </div>
        </div>

        <div className="sidebar__section">
          <div className="section-title">Sync status</div>
          <div className="status-card">
            <strong>{analysis ? 'Model result received from service X' : 'Waiting for model result'}</strong>
            <span>
              {analysis
                ? `${analysis.summary.totalNodes} nodes | ${analysis.summary.highCount} high | ${analysis.summary.lowCount} low`
                : 'Waiting for service payload'}
            </span>
          </div>
          <div className="status-card">
            <strong>
              {isSyncingService
                ? 'Saving graph to service X...'
                : hasUnsavedChanges
                  ? 'Draft changes waiting to be saved'
                  : 'Service X synced'}
            </strong>
            <span>{currentSnapshot.network.id}</span>
          </div>
        </div>
      </aside>

      <main className="canvas-shell">
        <div className="canvas-toolbar">
          <div className="toolbar-actions">
            <button className="toolbar-button" onClick={() => fitView({ padding: 0.18 })}>
              Fit graph
            </button>
            <button
              className={`toolbar-button ${isEditingGraph ? 'toolbar-button--secondary' : ''}`}
              onClick={() => setIsEditingGraph(true)}
              disabled={isEditingGraph}
            >
              Change graph
            </button>
            <button
              className="toolbar-button toolbar-button--accent"
              onClick={saveGraph}
              disabled={!isEditingGraph || !hasUnsavedChanges || isSyncingService}
            >
              Save graph
            </button>
            <button
              className="toolbar-button"
              onClick={removeSelectedNode}
              disabled={!selectedNode || !isEditingGraph}
            >
              Remove selected
            </button>
          </div>
          <div className="toolbar-hint">
            {isEditingGraph
              ? 'Link nodes by dragging from the right handle of one node to the left handle of another.'
              : 'Click Change graph to enable moving, linking, and editing nodes.'}
          </div>
          <div className="legend">
            <span><i className="legend__dot legend__dot--high" /> High</span>
            <span><i className="legend__dot legend__dot--low" /> Low</span>
            <span><i className="legend__dot legend__dot--normal" /> Normal</span>
            <span><i className="legend__dot legend__dot--off" /> Off</span>
          </div>
        </div>

        <div
          className="flow-wrapper"
          ref={wrapperRef}
          onDragOver={onDragOver}
          onDrop={onDrop}
        >
          <ReactFlow
            nodes={decoratedNodes}
            edges={edges}
            nodeTypes={nodeTypes}
            onNodesChange={onNodesChange}
            onEdgesChange={onEdgesChange}
            onConnect={onConnect}
            connectionMode={ConnectionMode.Loose}
            nodesDraggable={isEditingGraph}
            nodesConnectable={isEditingGraph}
            elementsSelectable
            fitView
            deleteKeyCode={['Backspace', 'Delete']}
            onSelectionChange={({ nodes: selectedNodes }) => {
              setSelectedNodeId(selectedNodes[0]?.id ?? null)
            }}
          >
            <MiniMap
              pannable
              zoomable
              className="minimap"
              nodeColor={(node) => severityColor((node.data as PowerNodeData).severity)}
            />
            <Controls />
            <Background variant={BackgroundVariant.Dots} gap={20} size={1.2} />
          </ReactFlow>
        </div>
      </main>

      <aside className="sidebar sidebar--right">
        <div className="sidebar__section">
          <div className="section-title">Selected node</div>
          {selectedNode ? (
            <div className="editor-card">
              <label>
                Label
                <input
                  value={selectedNode.data.label}
                  disabled={!isEditingGraph}
                  onChange={(event) => updateSelectedNode({ label: event.target.value })}
                />
              </label>
              <label>
                Nominal power (kW)
                <input
                  type="number"
                  min="0"
                  value={selectedNode.data.nominalPowerKw}
                  disabled={!isEditingGraph}
                  onChange={(event) =>
                    updateSelectedNode({
                      nominalPowerKw: Number(event.target.value) || 0,
                    })
                  }
                />
              </label>
              <label className="toggle">
                <input
                  type="checkbox"
                  checked={selectedNode.data.active}
                  disabled={!isEditingGraph}
                  onChange={(event) => updateSelectedNode({ active: event.target.checked })}
                />
                <span>Node active</span>
              </label>
              <div className={`chip chip--${selectedNodeSeverity ?? 'normal'}`}>
                {analysis?.nodes[selectedNode.id]
                  ? `${analysis.nodes[selectedNode.id].message} | ${Math.round(
                      analysis.nodes[selectedNode.id].estimatedPowerKw,
                    )} kW est.`
                  : selectedNode.data.message}
              </div>
              <div className="chip chip--normal">
                {selectedSensorReading
                  ? `Latest sensor: ${selectedSensorReading.powerKw} kW at ${new Date(
                      selectedSensorReading.timestamp,
                    ).toLocaleTimeString()}`
                  : 'No sensor reading for this node yet'}
              </div>
            </div>
          ) : (
            <div className="empty-card">Pick a node to inspect or edit it.</div>
          )}
        </div>

        <div className="sidebar__section">
          <div className="section-title">Problem actions</div>
          {visibleProblems.length > 0 ? (
            <div className="problem-list">
              {visibleProblems.map((problem) => (
                <div key={problem.id} className={`problem-card problem-card--${problem.severity}`}>
                  <div>
                    <strong>{problem.label}</strong>
                    <p>{problem.recommendation}</p>
                  </div>
                  <div className="problem-card__actions">
                    <button onClick={() => handleTurnOff(problem)} disabled={!isEditingGraph}>
                      Turn off
                    </button>
                    <button className="ghost-button" onClick={() => handleKeepAlive(problem)}>
                      No, it&apos;s fine
                    </button>
                  </div>
                </div>
              ))}
            </div>
          ) : (
            <div className="empty-card">No open issues right now.</div>
          )}
        </div>

        <div className="sidebar__section">
          <div className="section-title">Service X snapshot</div>
          <pre className="payload-preview">{JSON.stringify(currentSnapshot, null, 2)}</pre>
        </div>
      </aside>
    </div>
  )
}

function App() {
  return (
    <ReactFlowProvider>
      <FlowEditor />
    </ReactFlowProvider>
  )
}

function createNode(
  kind: PowerNodeKind,
  position: { x: number; y: number },
  explicitSequence?: number,
): PowerFlowNode {
  const template = NODE_TEMPLATES.find((item) => item.kind === kind)
  const sequence = explicitSequence ?? Date.now()
  const label = template ? template.label : 'Power Node'

  return {
    id: `node-${kind}-${sequence}`,
    type: 'powerNode',
    position,
    data: {
      id: `node-${kind}-${sequence}`,
      kind,
      label,
      nominalPowerKw: template?.nominalPowerKw ?? 50,
      active: true,
      severity: 'normal',
      message: 'Awaiting model run',
    },
  }
}

function severityColor(severity: Severity) {
  switch (severity) {
    case 'high':
      return '#d65d0e'
    case 'low':
      return '#2c73d2'
    case 'off':
      return '#5f646d'
    default:
      return '#2f8f5b'
  }
}

export default App
