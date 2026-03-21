import type { Edge } from '@xyflow/react'

import type {
  FrontendGraphState,
  GraphEdgeRecord,
  GraphNodeRecord,
  PowerFlowNode,
  ServiceSnapshot,
  SensorReadingRecord,
} from './types'

const SERVICE_X_BASE_URL =
  import.meta.env.VITE_SERVICE_X_URL ?? 'http://127.0.0.1:8000'

export async function fetchFrontendGraphState(): Promise<FrontendGraphState> {
  const response = await fetch(`${SERVICE_X_BASE_URL}/service-x/state`)
  if (!response.ok) {
    throw new Error('Failed to fetch Service X state')
  }
  return response.json() as Promise<FrontendGraphState>
}

export async function updateServiceGraph(
  networkId: string,
  graph: ServiceSnapshot['graph'],
): Promise<FrontendGraphState> {
  const response = await fetch(`${SERVICE_X_BASE_URL}/service-x/graph`, {
    method: 'PUT',
    headers: {
      'Content-Type': 'application/json',
    },
    body: JSON.stringify({
      networkId,
      graph,
    }),
  })
  if (!response.ok) {
    throw new Error(`Failed to update Service X graph for ${networkId}`)
  }
  return response.json() as Promise<FrontendGraphState>
}

export function snapshotToFlow(snapshot: ServiceSnapshot): {
  nodes: PowerFlowNode[]
  edges: Edge[]
  sensorReadings: SensorReadingRecord[]
} {
  return {
    nodes: snapshot.graph.nodes.map((node) => ({
      id: node.id,
      type: 'powerNode',
      position: {
        x: node.x,
        y: node.y,
      },
      data: {
        id: node.id,
        label: node.label,
        kind: node.type,
        nominalPowerKw: node.nominalPowerKw,
        active: node.active,
        severity: 'normal',
        message: 'Awaiting model run',
      },
    })),
    edges: snapshot.graph.edges.map((edge) => ({
      ...edge,
      animated: true,
    })),
    sensorReadings: snapshot.sensorReadings,
  }
}

export function flowToServiceSnapshot(
  networkId: string,
  networkName: string,
  nodes: PowerFlowNode[],
  edges: Edge[],
  sensorReadings: SensorReadingRecord[],
): ServiceSnapshot {
  const graphNodes: GraphNodeRecord[] = nodes.map((node) => ({
    id: node.id,
    type: node.data.kind,
    label: node.data.label,
    x: Math.round(node.position.x),
    y: Math.round(node.position.y),
    nominalPowerKw: node.data.nominalPowerKw,
    active: node.data.active,
  }))

  const graphEdges: GraphEdgeRecord[] = edges.map((edge) => ({
    id: edge.id,
    source: edge.source,
    target: edge.target,
  }))

  return {
    network: {
      id: networkId,
      name: networkName,
    },
    graph: {
      nodes: graphNodes,
      edges: graphEdges,
    },
    sensorReadings,
  }
}
