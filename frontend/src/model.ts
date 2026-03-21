import type {
  ModelAnalysis,
  ModelPayload,
  PowerNodeKind,
  ProblemNode,
  ServiceSnapshot,
  Severity,
} from './types'

const TYPE_BASELINE: Record<PowerNodeKind, number> = {
  source: 110,
  transformer: 82,
  transmission: 58,
  battery: 36,
  sink: 74,
}

export function buildModelPayload(snapshot: ServiceSnapshot): ModelPayload {
  return {
    networkId: snapshot.network.id,
    graph: {
      nodes: snapshot.graph.nodes,
      edges: snapshot.graph.edges,
    },
    sensorReadings: snapshot.sensorReadings,
    telemetry: {
      sentAt: new Date().toISOString(),
      mode: 'service-sync',
    },
  }
}

export async function analyzeGraph(
  snapshot: ServiceSnapshot,
): Promise<ModelAnalysis> {
  const payload = buildModelPayload(snapshot)

  await new Promise((resolve) => {
    window.setTimeout(resolve, 220)
  })

  const problems: ProblemNode[] = []
  const nodeResults = Object.fromEntries(
    payload.graph.nodes.map((node) => {
      const connectedEdges = payload.graph.edges.filter(
        (edge) => edge.source === node.id || edge.target === node.id,
      ).length

      const activeFactor = node.active ? 1 : 0
      const sensorReading = payload.sensorReadings.find(
        (reading) => reading.nodeId === node.id,
      )
      const measuredPowerKw = sensorReading?.powerKw ?? node.nominalPowerKw
      const estimatedPowerKw = measuredPowerKw * activeFactor + connectedEdges * 6
      const baseline = TYPE_BASELINE[node.type]

      let severity: Severity = 'normal'
      let message = sensorReading ? 'Reading in range' : 'Estimated from network'

      if (!node.active) {
        severity = 'off'
        message = 'Isolated by operator'
      } else if (estimatedPowerKw > baseline * 1.15) {
        severity = 'high'
        message = 'High draw detected'
      } else if (estimatedPowerKw < baseline * 0.65) {
        severity = 'low'
        message = 'Low draw detected'
      }

      if (severity === 'high' || severity === 'low') {
        problems.push({
          id: node.id,
          label: node.label,
          severity,
          recommendation:
            severity === 'high'
              ? 'Turn off this path for now or push an update to service X.'
              : 'Keep it running or confirm the low draw is expected.',
        })
      }

      return [
        node.id,
        {
          severity,
          message,
          estimatedPowerKw,
        },
      ]
    }),
  ) as ModelAnalysis['nodes']

  return {
    payload,
    nodes: nodeResults,
    problems,
    summary: {
      highCount: problems.filter((problem) => problem.severity === 'high').length,
      lowCount: problems.filter((problem) => problem.severity === 'low').length,
      totalNodes: payload.graph.nodes.length,
    },
  }
}
