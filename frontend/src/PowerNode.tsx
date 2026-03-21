import type { NodeProps } from '@xyflow/react'
import { Handle, Position } from '@xyflow/react'

import type { PowerFlowNode, PowerNodeKind } from './types'

const KIND_LABEL: Record<PowerNodeKind, string> = {
  source: 'Source',
  battery: 'Battery',
  transformer: 'Transformer',
  transmission: 'Transmission',
  sink: 'Sink',
}

export function PowerNode({ data, selected }: NodeProps<PowerFlowNode>) {
  return (
    <div
      className={[
        'power-node',
        `power-node--${data.severity}`,
        selected ? 'power-node--selected' : '',
      ]
        .filter(Boolean)
        .join(' ')}
    >
      <Handle
        className="power-node__handle"
        type="target"
        position={Position.Left}
        isConnectable
      />
      <div className="power-node__topline">
        <span className="power-node__kind">{KIND_LABEL[data.kind]}</span>
        <span className="power-node__badge">{data.active ? 'Live' : 'Off'}</span>
      </div>
      <strong className="power-node__label">{data.label}</strong>
      <div className="power-node__metric">{Math.round(data.nominalPowerKw)} kW nominal</div>
      <div className="power-node__message">{data.message}</div>
      <Handle
        className="power-node__handle"
        type="source"
        position={Position.Right}
        isConnectable
      />
    </div>
  )
}
