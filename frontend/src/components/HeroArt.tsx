/**
 * Композиция в правой части обложки главной и панели входа.
 *
 * Каркасная голова из брендбука (фон плитки снят, края растворены в
 * обложке), вокруг неё — светящаяся орбита и три стеклянные плашки с тем,
 * что делает платформа. Орбита разрезана на две дуги: задняя проходит за
 * головой, передняя — поверх неё, поэтому кольцо читается объёмным.
 * Всё декоративное скрыто от скринридера: смысл дублируется текстом слева
 * и полосой цифр ниже.
 */

const CX = 280;
const CY = 300;
const RX = 262;
const RY = 70;
const TILT = -13;

/** Точка на эллипсе орбиты (угол в градусах, 0 — справа, против часовой — вверх). */
function onOrbit(deg: number) {
  const t = (deg * Math.PI) / 180;
  return { x: CX + RX * Math.cos(t), y: CY - RY * Math.sin(t) };
}

function Orbit({ part }: { part: 'back' | 'front' }) {
  // задняя дуга — верхняя половина эллипса, передняя — нижняя
  const d =
    part === 'back'
      ? `M ${CX - RX} ${CY} A ${RX} ${RY} 0 0 1 ${CX + RX} ${CY}`
      : `M ${CX + RX} ${CY} A ${RX} ${RY} 0 0 1 ${CX - RX} ${CY}`;
  const dots = part === 'back' ? [onOrbit(128), onOrbit(38)] : [onOrbit(-62)];
  return (
    <svg className={`art-orbit art-orbit-${part}`} viewBox="0 0 560 520" fill="none">
      <defs>
        <linearGradient id={`orbit-${part}`} x1="0" y1="0" x2="1" y2="0">
          <stop offset="0" stopColor="#8f85ff" stopOpacity={part === 'back' ? 0.25 : 0.9} />
          <stop offset="0.5" stopColor="#b9b3ff" stopOpacity={part === 'back' ? 0.55 : 1} />
          <stop offset="1" stopColor="#6f61ff" stopOpacity={part === 'back' ? 0.3 : 0.85} />
        </linearGradient>
      </defs>
      <g transform={`rotate(${TILT} ${CX} ${CY})`}>
        <path d={d} stroke={`url(#orbit-${part})`} strokeWidth={part === 'back' ? 1.4 : 2} />
        {dots.map((p) => (
          <circle key={`${p.x}-${p.y}`} className="art-orbit-dot" cx={p.x} cy={p.y} r={part === 'back' ? 3 : 4} />
        ))}
      </g>
    </svg>
  );
}

export default function HeroArt() {
  return (
    <div className="art" aria-hidden>
      <div className="art-glow" />
      <Orbit part="back" />
      <img className="art-head" src="/brand/head.webp" alt="" width={664} height={626} />
      <Orbit part="front" />

      <img className="art-plate art-plate-testing" src="/brand/plate-testing.webp" alt="" width={520} height={361} />
      <img className="art-plate art-plate-matching" src="/brand/plate-matching.webp" alt="" width={520} height={458} />
      <img
        className="art-plate art-plate-qualification"
        src="/brand/plate-qualification.webp"
        alt=""
        width={520}
        height={331}
      />
    </div>
  );
}
