import { useMemo } from 'react'
import { BrutalistCard } from './ui/BrutalistCard'
import { PoolStatus, HeartbeatConfig } from 'lib/api'

interface StatsGridProps {
  data: PoolStatus
  hbConfig: HeartbeatConfig | null
}

export function StatsGrid({ data, hbConfig }: StatsGridProps) {
  const enabledCount = useMemo(
    () => (data.clients || []).filter((c) => c.enabled).length,
    [data.clients]
  )

  const getHeartbeatStatus = () => {
    if (!hbConfig) return { label: 'UNKNOWN', color: 'text-gray-500' }
    if (!hbConfig.enable) return { label: 'DISABLED', color: 'text-gray-500' }
    return { label: 'ACTIVE', color: 'text-green-500' }
  }

  const hbStatus = getHeartbeatStatus()

  return (
    <div className="grid grid-cols-2 md:grid-cols-4 gap-6 mb-12">
      <BrutalistCard
        number="01"
        label="Total Clients"
        value={data.total || 0}
        colorClass="text-acid"
      />
      <BrutalistCard
        number="02"
        label="Available"
        value={data.available || 0}
        colorClass="text-neon-blue"
      />
      <BrutalistCard
        number="03"
        label="Enabled"
        value={enabledCount}
        colorClass="text-neon-pink"
      />
      <BrutalistCard
        number="04"
        label="Heartbeat"
        value={hbStatus.label}
        colorClass={hbStatus.color}
      />
    </div>
  )
}
