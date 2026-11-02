// ─────────────────────────────────────────────────────────────────────────────
// TrendSparkline
// SVG sparkline with filled area gradient and animated draw-on effect
// ─────────────────────────────────────────────────────────────────────────────

export default function TrendSparkline({ data, color = "#00e5ff" }) {
  if (!data || data.length < 2) return null;

  const W = 308;
  const H = 56;

  const min = Math.min(...data);
  const max = Math.max(...data);

  const scaleY = (v) => H - ((v - min) / (max - min + 0.01)) * (H - 8) - 4;
  const scaleX = (i) => (i / (data.length - 1)) * W;

  // Build smooth cubic-bezier path
  let linePath = `M ${scaleX(0)} ${scaleY(data[0])}`;
  for (let i = 1; i < data.length; i++) {
    const cx = (scaleX(i - 1) + scaleX(i)) / 2;
    linePath += ` C ${cx} ${scaleY(data[i - 1])}, ${cx} ${scaleY(data[i])}, ${scaleX(i)} ${scaleY(data[i])}`;
  }

  const areaPath = `${linePath} L ${scaleX(data.length - 1)} ${H} L 0 ${H} Z`;
  const gradId   = `trendGrad-${color.replace(/[^a-z0-9]/gi, "")}`;

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      preserveAspectRatio="none"
      style={{ width:"100%", height:"100%", display:"block" }}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%"   stopColor={color} stopOpacity="0.28" />
          <stop offset="100%" stopColor={color} stopOpacity="0"    />
        </linearGradient>
      </defs>

      {/* Filled area */}
      <path d={areaPath} fill={`url(#${gradId})`} />

      {/* Animated line */}
      <path
        d={linePath}
        className="trend-path"
        fill="none"
        stroke={color}
        strokeWidth="1.5"
        opacity="0.9"
      />

      {/* End-point dot */}
      <circle
        cx={scaleX(data.length - 1)}
        cy={scaleY(data[data.length - 1])}
        r="2.5"
        fill={color}
        style={{ filter:`drop-shadow(0 0 4px ${color})` }}
      />
    </svg>
  );
}
