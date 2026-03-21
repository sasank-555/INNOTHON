import type { Node } from '@xyflow/react'

export type PowerNodeKind =
  | 'source'
  | 'battery'
  | 'transformer'
  | 'transmission'
  | 'sink'

export type Severity = 'normal' | 'low' | 'high' | 'off'

export type PowerNodeData = {
  id: string
  label: string
  kind: PowerNodeKind
  nominalPowerKw: number
  active: boolean
  severity: Severity
  message: string
}

export type PowerFlowNode = Node<PowerNodeData, 'powerNode'>

export type GraphNodeRecord = {
  id: string
  type: PowerNodeKind
  label: string
  x: number
  y: number
  nominalPowerKw: number
  active: boolean
}

export type GraphEdgeRecord = {
  id: string
  source: string
  target: string
}

export type SensorReadingRecord = {
  nodeId: string
  powerKw: number
  voltageKv?: number
  timestamp: string
}

export type ServiceSnapshot = {
  network: {
    id: string
    name: string
  }
  graph: {
    nodes: GraphNodeRecord[]
    edges: GraphEdgeRecord[]
  }
  sensorReadings: SensorReadingRecord[]
}

export type ModelPayload = {
  networkId: string
  graph: {
    nodes: GraphNodeRecord[]
    edges: GraphEdgeRecord[]
  }
  sensorReadings: SensorReadingRecord[]
  telemetry: {
    sentAt: string
    mode: 'service-sync'
  }
}

export type ProblemNode = {
  id: string
  label: string
  severity: Exclude<Severity, 'normal'>
  recommendation: string
}

export type ModelAnalysis = {
  payload: ModelPayload
  nodes: Record<
    string,
    {
      severity: Severity
      message: string
      estimatedPowerKw: number
    }
  >
  problems: ProblemNode[]
  summary: {
    highCount: number
    lowCount: number
    totalNodes: number
  }
}

export type FrontendGraphState = {
  snapshot: ServiceSnapshot
  analysis: ModelAnalysis
}
