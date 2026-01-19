interface BrutalistCardProps {
  number: string
  label: string
  value: string | number
  colorClass: string
}

export function BrutalistCard({ number, label, value, colorClass }: BrutalistCardProps) {
  return (
    <div className="brutalist-card p-6 relative group overflow-hidden">
      <div
        className={`absolute top-0 right-0 p-2 opacity-20 font-black text-6xl text-gray-700 pointer-events-none group-hover:${colorClass} transition-colors`}
      >
        {number}
      </div>
      <div className="text-xs font-mono uppercase tracking-widest text-gray-500 mb-2">
        {label}
      </div>
      <div
        className={`text-4xl md:text-5xl font-black text-white group-hover:${colorClass} transition-colors truncate`}
      >
        {value}
      </div>
    </div>
  )
}
