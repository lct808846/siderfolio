<script setup lang="ts">
import { useAppearance } from '../stores/appearance'

const appearance = useAppearance()

interface StarPoint {
  x: number
  y: number
  r: number
  tone: 'primary' | 'secondary' | 'tertiary'
  phase: 0 | 1 | 2
}

interface ConstellationStar {
  x: number
  y: number
  r: number
  spark: boolean
  halo: 'primary' | 'secondary'
  phase: 0 | 1 | 2
}

const fieldStars: readonly StarPoint[] = [
  { x: 124, y: 152, r: 1.8, tone: 'primary', phase: 0 },
  { x: 218, y: 266, r: 1.5, tone: 'secondary', phase: 1 },
  { x: 288, y: 118, r: 2.1, tone: 'tertiary', phase: 2 },
  { x: 454, y: 102, r: 1.6, tone: 'primary', phase: 1 },
  { x: 562, y: 248, r: 1.5, tone: 'secondary', phase: 0 },
  { x: 658, y: 128, r: 2.0, tone: 'primary', phase: 2 },
  { x: 742, y: 196, r: 1.4, tone: 'tertiary', phase: 1 },
  { x: 836, y: 106, r: 1.9, tone: 'secondary', phase: 0 },
  { x: 938, y: 168, r: 1.6, tone: 'primary', phase: 2 },
  { x: 1016, y: 92, r: 1.4, tone: 'tertiary', phase: 1 },
  { x: 1474, y: 148, r: 2.0, tone: 'secondary', phase: 0 },
  { x: 1518, y: 294, r: 1.6, tone: 'primary', phase: 2 },
  { x: 1456, y: 462, r: 2.2, tone: 'tertiary', phase: 0 },
  { x: 1362, y: 558, r: 1.5, tone: 'primary', phase: 1 },
  { x: 1528, y: 632, r: 1.8, tone: 'secondary', phase: 2 },
  { x: 1482, y: 842, r: 1.5, tone: 'primary', phase: 1 },
  { x: 1214, y: 882, r: 1.9, tone: 'tertiary', phase: 0 },
  { x: 982, y: 816, r: 1.6, tone: 'secondary', phase: 2 },
  { x: 868, y: 888, r: 2.0, tone: 'primary', phase: 0 },
  { x: 744, y: 786, r: 1.4, tone: 'primary', phase: 1 },
  { x: 642, y: 864, r: 1.8, tone: 'secondary', phase: 2 },
  { x: 526, y: 726, r: 1.5, tone: 'tertiary', phase: 1 },
  { x: 438, y: 638, r: 1.7, tone: 'primary', phase: 0 },
  { x: 172, y: 424, r: 1.9, tone: 'secondary', phase: 2 },
  { x: 256, y: 492, r: 1.4, tone: 'primary', phase: 1 },
  { x: 136, y: 622, r: 1.8, tone: 'tertiary', phase: 0 },
  { x: 356, y: 382, r: 1.5, tone: 'primary', phase: 2 },
  { x: 964, y: 522, r: 1.5, tone: 'secondary', phase: 1 },
  { x: 1094, y: 584, r: 1.7, tone: 'tertiary', phase: 0 },
  { x: 696, y: 642, r: 1.4, tone: 'primary', phase: 2 },
]

const constellationStars: readonly ConstellationStar[] = [
  // Cassiopeia W-Asterism
  { x: 358, y: 178, r: 2.8, spark: false, halo: 'primary', phase: 0 },
  { x: 422, y: 230, r: 3.4, spark: true, halo: 'primary', phase: 1 },
  { x: 486, y: 196, r: 2.6, spark: false, halo: 'primary', phase: 2 },
  { x: 544, y: 252, r: 3.1, spark: false, halo: 'primary', phase: 0 },
  { x: 616, y: 204, r: 2.7, spark: true, halo: 'primary', phase: 2 },
  // Big Dipper / Ursa Major
  { x: 1036, y: 746, r: 2.7, spark: false, halo: 'secondary', phase: 1 },
  { x: 1108, y: 714, r: 3.0, spark: false, halo: 'secondary', phase: 0 },
  { x: 1178, y: 726, r: 2.8, spark: false, halo: 'secondary', phase: 2 },
  { x: 1244, y: 758, r: 3.2, spark: true, halo: 'secondary', phase: 1 },
  { x: 1264, y: 822, r: 2.6, spark: false, halo: 'secondary', phase: 0 },
  { x: 1364, y: 806, r: 3.0, spark: false, halo: 'secondary', phase: 2 },
  { x: 1352, y: 732, r: 3.4, spark: true, halo: 'secondary', phase: 1 },
]

// Partition twinkling stars into 3 GPU-composited opacity layers so every star
// keeps organic staggered breathing with zero per-frame SVG CPU re-rasterization.
const starPhases = ([0, 1, 2] as const).map(phase => ({
  phase,
  field: fieldStars.filter(star => star.phase === phase),
  constellation: constellationStars.filter(star => star.phase === phase),
}))

const orreryTicks = Array.from({ length: 12 }, (_, idx) => idx * 30)
</script>

<template>
  <div
    class="astro-backdrop"
    :class="{
      'is-static': !appearance.astroMotion || appearance.reducedMotion,
      'no-ambient': !appearance.ambientBg,
    }"
    aria-hidden="true"
  >
    <!-- Galactic nebula wash & diagonal Milky Way mist -->
    <div class="astro-galactic-band" />
    <div class="astro-nebula astro-nebula-a" />
    <div class="astro-nebula astro-nebula-b" />
    <div class="astro-nebula astro-nebula-c" />

    <!-- Aspect-locked 5:3 stage matching viewBox 0 0 1600 960 preserveAspectRatio="xMidYMid slice" -->
    <div class="astro-sky-stage">
      <!-- 100% static celestial geometry: rasterized once on GPU, 0ms/frame afterwards -->
      <svg class="astro-sky astro-sky-static" viewBox="0 0 1600 960" fill="none">
        <defs>
          <linearGradient id="astro-orbit-grad-main" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0.14" />
            <stop offset="40%" style="stop-color: var(--astro-primary); stop-opacity: 0.92" />
            <stop offset="72%" style="stop-color: var(--astro-secondary); stop-opacity: 0.85" />
            <stop offset="100%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.16" />
          </linearGradient>
          <linearGradient id="astro-horizon-grad" x1="0%" y1="50%" x2="100%" y2="50%">
            <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
            <stop offset="28%" style="stop-color: var(--astro-primary); stop-opacity: 0.88" />
            <stop offset="56%" style="stop-color: var(--astro-secondary); stop-opacity: 0.95" />
            <stop offset="82%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.64" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          </linearGradient>
          <radialGradient id="astro-horizon-glow" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.36" />
            <stop offset="52%" style="stop-color: var(--astro-primary); stop-opacity: 0.16" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          </radialGradient>
        </defs>

        <!-- Grand Keplerian Orrery & Astrolabe static rings & ticks -->
        <g class="astro-geometry" transform="translate(1228 272)">
          <circle r="258" class="astro-ring-dashed" />
          <circle r="172" class="astro-ring-fine" />
          <circle r="96" class="astro-ring-inner" />
          <ellipse rx="344" ry="128" transform="rotate(-24)" stroke="url(#astro-orbit-grad-main)" stroke-width="1.45" />
          <ellipse rx="296" ry="96" transform="rotate(18)" class="astro-ring-dashed" />
          <g class="astro-ticks">
            <line
              v-for="deg in orreryTicks"
              :key="`tick-${deg}`"
              x1="0"
              y1="-250"
              x2="0"
              :y2="deg % 90 === 0 ? -268 : -261"
              :transform="`rotate(${deg})`"
            />
          </g>
        </g>

        <!-- Lower-Left Eclipse Horizon Limb & Celestial Meridian Arcs -->
        <g class="astro-geometry" transform="translate(310 856)">
          <ellipse rx="460" ry="205" transform="rotate(-9)" fill="url(#astro-horizon-glow)" />
          <ellipse rx="476" ry="214" transform="rotate(-9)" stroke="url(#astro-horizon-grad)" stroke-width="1.8" />
          <ellipse rx="418" ry="184" transform="rotate(-9)" class="astro-ring-dashed" />
          <circle r="326" class="astro-ring-fine" stroke-dasharray="4 10" />
        </g>

        <!-- Constellation lines (Cassiopeia + Big Dipper) -->
        <g class="astro-constellation">
          <polyline points="358,178 422,230 486,196 544,252 616,204" class="astro-constellation-line" />
          <polyline
            points="1036,746 1108,714 1178,726 1244,758 1264,822 1364,806 1352,732 1244,758"
            class="astro-constellation-line"
          />
        </g>
      </svg>

      <!-- 3 Staggered GPU-composited twinkling starfield & constellation star layers -->
      <svg
        v-for="group in starPhases"
        :key="`stars-p${group.phase}`"
        class="astro-sky astro-star-layer"
        :class="`astro-star-phase-${group.phase}`"
        viewBox="0 0 1600 960"
        fill="none"
      >
        <defs>
          <radialGradient :id="`astro-halo-p-${group.phase}`" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0.88" />
            <stop offset="48%" style="stop-color: var(--astro-primary); stop-opacity: 0.32" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          </radialGradient>
          <radialGradient :id="`astro-halo-s-${group.phase}`" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
            <stop offset="48%" style="stop-color: var(--astro-secondary); stop-opacity: 0.34" />
            <stop offset="100%" style="stop-color: var(--astro-secondary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-constellation">
          <g v-for="star in group.constellation" :key="`cs-${star.x}-${star.y}`">
            <circle
              :cx="star.x"
              :cy="star.y"
              :r="star.spark ? (star.halo === 'secondary' ? 17 : 16) : (star.halo === 'secondary' ? 9.5 : 9)"
              :fill="`url(#astro-halo-${star.halo === 'secondary' ? 's' : 'p'}-${group.phase})`"
            />
            <path
              v-if="star.spark"
              :d="star.halo === 'secondary'
                ? `M ${star.x} ${star.y - 11} L ${star.x + 2.1} ${star.y - 2.1} L ${star.x + 11} ${star.y} L ${star.x + 2.1} ${star.y + 2.1} L ${star.x} ${star.y + 11} L ${star.x - 2.1} ${star.y + 2.1} L ${star.x - 11} ${star.y} L ${star.x - 2.1} ${star.y - 2.1} Z`
                : `M ${star.x} ${star.y - 10.5} L ${star.x + 2} ${star.y - 2} L ${star.x + 10.5} ${star.y} L ${star.x + 2} ${star.y + 2} L ${star.x} ${star.y + 10.5} L ${star.x - 2} ${star.y + 2} L ${star.x - 10.5} ${star.y} L ${star.x - 2} ${star.y - 2} Z`"
              :class="star.halo === 'secondary' ? 'astro-star-secondary' : 'astro-star-primary'"
            />
            <circle v-else :cx="star.x" :cy="star.y" :r="star.r" class="astro-star-primary" />
          </g>
        </g>
        <g class="astro-field-stars">
          <circle
            v-for="star in group.field"
            :key="`fs-${star.x}-${star.y}`"
            :cx="star.x"
            :cy="star.y"
            :r="star.r"
            :class="`astro-star-${star.tone}`"
          />
        </g>
      </svg>

      <!-- Compact GPU-composited orbital & celestial sprites (rasterized once, transformed on GPU) -->

      <!-- Central luminous star core (1228, 272) -->
      <svg class="astro-sprite astro-core-pulse" viewBox="-56 -56 112 112" fill="none">
        <defs>
          <radialGradient id="astro-sun-corona" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
            <stop offset="32%" style="stop-color: var(--astro-primary); stop-opacity: 0.48" />
            <stop offset="68%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.18" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-geometry">
          <circle r="48" fill="url(#astro-sun-corona)" />
          <circle r="11" class="astro-ring-fine" />
          <path d="M 0 -13 L 2.4 -2.4 L 13 0 L 2.4 2.4 L 0 13 L -2.4 2.4 L -13 0 L -2.4 -2.4 Z" class="astro-star-secondary" />
          <circle r="4.2" class="astro-star-primary" />
        </g>
      </svg>

      <!-- Fast inner planet with curved luminous wake (1228, 272) -->
      <svg class="astro-sprite astro-orbit-fast" viewBox="-120 -120 240 240" fill="none">
        <defs>
          <linearGradient id="astro-wake-grad" x1="0%" y1="0%" x2="100%" y2="100%">
            <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0.9" />
          </linearGradient>
          <radialGradient id="astro-node-halo-primary" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0.88" />
            <stop offset="48%" style="stop-color: var(--astro-primary); stop-opacity: 0.32" />
            <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-geometry">
          <path d="M 0 -96 A 96 96 0 0 1 96 0" stroke="url(#astro-wake-grad)" stroke-width="2" stroke-linecap="round" />
          <circle cx="96" cy="0" r="16" fill="url(#astro-node-halo-primary)" />
          <circle cx="96" cy="0" r="4.2" class="astro-star-primary" />
        </g>
      </svg>

      <!-- Mid-orbit ringed Saturn-like planet CCW (1228, 272) -->
      <svg class="astro-sprite astro-orbit-mid" viewBox="-200 -200 400 400" fill="none">
        <defs>
          <radialGradient id="astro-node-halo-secondary" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
            <stop offset="48%" style="stop-color: var(--astro-secondary); stop-opacity: 0.34" />
            <stop offset="100%" style="stop-color: var(--astro-secondary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-geometry">
          <path d="M 124 -120 A 172 172 0 0 1 172 0" class="astro-arc-secondary" />
          <g transform="translate(172 0)">
            <circle r="20" fill="url(#astro-node-halo-secondary)" />
            <ellipse rx="14" ry="4.5" transform="rotate(-26)" class="astro-planet-ring" />
            <circle r="5.2" class="astro-star-secondary" />
            <path d="M -11 5 A 14 4.5 -26 0 0 11 -5" class="astro-planet-ring-front" />
          </g>
        </g>
      </svg>

      <!-- Outer comet/moon system CW (1228, 272) -->
      <div class="astro-sprite astro-orbit-slow">
        <svg class="astro-sprite-fill" viewBox="-284 -284 568 568" fill="none">
          <defs>
            <radialGradient id="astro-node-halo-tertiary" cx="50%" cy="50%" r="50%">
              <stop offset="0%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.88" />
              <stop offset="50%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.3" />
              <stop offset="100%" style="stop-color: var(--astro-tertiary); stop-opacity: 0" />
            </radialGradient>
          </defs>
          <g class="astro-geometry">
            <path d="M -216 -140 A 258 258 0 0 0 -258 0" class="astro-arc-tertiary" />
            <g transform="translate(-258 0)">
              <circle r="18" fill="url(#astro-node-halo-tertiary)" />
              <circle r="4.4" class="astro-star-tertiary" />
              <circle r="13" class="astro-ring-inner" />
            </g>
          </g>
        </svg>
        <svg class="astro-moon-spin" viewBox="-18 -18 36 36" fill="none">
          <g class="astro-geometry">
            <circle cx="13" cy="0" r="2.1" class="astro-star-primary" />
          </g>
        </svg>
      </div>

      <!-- Lower-left horizon meridian satellite CW (310, 856) -->
      <svg class="astro-sprite astro-orbit-horizon" viewBox="-352 -352 704 704" fill="none">
        <defs>
          <radialGradient id="astro-node-halo-horizon" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
            <stop offset="48%" style="stop-color: var(--astro-secondary); stop-opacity: 0.34" />
            <stop offset="100%" style="stop-color: var(--astro-secondary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-geometry">
          <path d="M -118 -304 A 326 326 0 0 1 0 -326" class="astro-arc-secondary" />
          <circle cx="0" cy="-326" r="18" fill="url(#astro-node-halo-horizon)" />
          <circle cx="0" cy="-326" r="4.2" class="astro-star-secondary" />
        </g>
      </svg>

      <!-- Mid-Left Minimalist Crescent Moon & Halo (292, 528) -->
      <svg class="astro-sprite astro-lunar-float" viewBox="-40 -40 80 80" fill="none">
        <defs>
          <radialGradient id="astro-node-halo-moon" cx="50%" cy="50%" r="50%">
            <stop offset="0%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.88" />
            <stop offset="50%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.3" />
            <stop offset="100%" style="stop-color: var(--astro-tertiary); stop-opacity: 0" />
          </radialGradient>
        </defs>
        <g class="astro-geometry">
          <circle r="34" fill="url(#astro-node-halo-moon)" />
          <circle r="24" class="astro-ring-dashed" />
          <path
            d="M 4 -14 A 14.5 14.5 0 1 0 14 7.5 A 11.4 11.4 0 1 1 4 -14 Z"
            class="astro-star-secondary"
          />
        </g>
      </svg>
    </div>

    <!-- 3 Staggered Graceful Shooting Stars -->
    <span class="astro-meteor astro-meteor-a" />
    <span class="astro-meteor astro-meteor-b" />
    <span class="astro-meteor astro-meteor-c" />
  </div>
</template>

<style scoped>
.astro-backdrop {
  position: fixed;
  inset: 0;
  z-index: 0;
  overflow: hidden;
  pointer-events: none;
  background: var(--workspace-scene);
  contain: strict;
}

.astro-galactic-band {
  position: absolute;
  top: 50%;
  left: 50%;
  width: 156vmax;
  height: 52vmax;
  transform: translate3d(-50%, -50%, 0) rotate(-24deg);
  background: radial-gradient(
    ellipse 58% 44% at 50% 50%,
    var(--astro-glow-a) 0%,
    var(--astro-glow-b) 42%,
    var(--astro-glow-c) 68%,
    transparent 86%
  );
  opacity: 0.98;
  will-change: transform, opacity;
  animation: astro-band-breathe 14s ease-in-out infinite;
}

.astro-nebula {
  position: absolute;
  border-radius: 50%;
  will-change: transform, opacity;
}

.astro-nebula-a {
  top: -150px;
  right: -20px;
  width: 820px;
  height: 700px;
  background: radial-gradient(circle, var(--astro-glow-a) 0%, transparent 68%);
  animation: astro-nebula-drift 12s ease-in-out infinite;
}

.astro-nebula-b {
  bottom: -170px;
  left: -30px;
  width: 860px;
  height: 700px;
  background: radial-gradient(circle, var(--astro-glow-b) 0%, transparent 68%);
  animation: astro-nebula-drift 15s ease-in-out infinite reverse;
}

.astro-nebula-c {
  top: 26%;
  left: 30%;
  width: 660px;
  height: 560px;
  background: radial-gradient(circle, var(--astro-glow-c) 0%, transparent 70%);
  animation: astro-nebula-drift 19s ease-in-out infinite -5s;
}

.astro-sky-stage {
  position: absolute;
  top: 50%;
  left: 50%;
  width: max(100vw, 166.6667dvh);
  height: max(100dvh, 60vw);
  transform: translate3d(-50%, -50%, 0);
  contain: layout style;
}

.astro-sky {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
}

.astro-star-layer {
  contain: strict;
  will-change: opacity;
  transform: translateZ(0);
}

.astro-star-phase-0 {
  animation: astro-star-breathe 3.8s ease-in-out infinite -0.7s;
}

.astro-star-phase-1 {
  animation: astro-star-breathe 4.7s ease-in-out infinite -2.1s;
}

.astro-star-phase-2 {
  animation: astro-star-breathe 5.5s ease-in-out infinite -3.4s;
}

.astro-sprite {
  position: absolute;
  display: block;
  overflow: visible;
  contain: layout style;
  will-change: transform;
  transform: translate3d(-50%, -50%, 0);
}

.astro-sprite-fill {
  display: block;
  width: 100%;
  height: 100%;
}

.astro-geometry {
  opacity: var(--astro-stroke-alpha);
}

.astro-ring-fine {
  stroke: var(--astro-primary);
  stroke-width: 1.45;
  stroke-opacity: 0.84;
}

.astro-ring-inner {
  stroke: var(--astro-tertiary);
  stroke-width: 1.25;
  stroke-opacity: 0.72;
  stroke-dasharray: 2 5;
}

.astro-ring-dashed {
  stroke: var(--astro-primary);
  stroke-width: 1.3;
  stroke-opacity: 0.68;
  stroke-dasharray: 4 9;
}

.astro-ticks {
  stroke: var(--astro-primary);
  stroke-width: 1.4;
  stroke-opacity: 0.82;
  stroke-linecap: round;
}

.astro-arc-secondary {
  stroke: var(--astro-secondary);
  stroke-width: 2.3;
  stroke-opacity: 0.94;
  stroke-linecap: round;
}

.astro-arc-tertiary {
  stroke: var(--astro-tertiary);
  stroke-width: 2;
  stroke-opacity: 0.9;
  stroke-linecap: round;
}

.astro-planet-ring {
  stroke: var(--astro-primary);
  stroke-width: 1.75;
  stroke-opacity: 0.9;
}

.astro-planet-ring-front {
  stroke: var(--astro-secondary);
  stroke-width: 1.75;
  stroke-opacity: 0.96;
  stroke-linecap: round;
}

.astro-constellation {
  opacity: var(--astro-star-alpha);
}

.astro-constellation-line {
  stroke: var(--astro-primary);
  stroke-width: 1.35;
  stroke-opacity: 0.72;
  stroke-dasharray: 3 4;
}

.astro-field-stars {
  opacity: var(--astro-star-alpha);
}

.astro-star-primary {
  fill: var(--astro-primary);
}

.astro-star-secondary {
  fill: var(--astro-secondary);
}

.astro-star-tertiary {
  fill: var(--astro-tertiary);
}

/* Exact coordinates relative to 1600x960 stage */
.astro-core-pulse {
  left: 76.75%;
  top: 28.3333%;
  width: 7%;
  height: 11.6667%;
  will-change: transform, opacity;
  animation: astro-core-breathe 3.8s ease-in-out infinite;
}

.astro-orbit-fast {
  left: 76.75%;
  top: 28.3333%;
  width: 15%;
  height: 25%;
  animation: astro-spin-cw 13s linear infinite;
}

.astro-orbit-mid {
  left: 76.75%;
  top: 28.3333%;
  width: 25%;
  height: 41.6667%;
  animation: astro-spin-ccw 26s linear infinite;
}

.astro-orbit-slow {
  left: 76.75%;
  top: 28.3333%;
  width: 35.5%;
  height: 59.1667%;
  animation: astro-spin-cw 42s linear infinite;
}

.astro-moon-spin {
  position: absolute;
  left: 4.5775%;
  top: 50%;
  width: 6.338%;
  height: 6.338%;
  will-change: transform;
  transform: translate3d(-50%, -50%, 0);
  animation: astro-spin-ccw 5s linear infinite;
}

.astro-orbit-horizon {
  left: 19.375%;
  top: 89.1667%;
  width: 44%;
  height: 73.3333%;
  animation: astro-spin-cw 30s linear infinite;
}

.astro-lunar-float {
  left: 18.25%;
  top: 55%;
  width: 5%;
  height: 8.3333%;
  animation: astro-lunar-bob 6s ease-in-out infinite;
}

.astro-meteor {
  position: absolute;
  width: 210px;
  height: 2.5px;
  border-radius: 999px;
  background: linear-gradient(90deg, transparent 0%, var(--astro-tertiary) 40%, var(--astro-secondary) 82%, #fff 100%);
  opacity: 0;
  will-change: transform, opacity;
}

.astro-meteor::after {
  content: '';
  position: absolute;
  right: -2px;
  top: 50%;
  width: 6px;
  height: 6px;
  border-radius: 50%;
  transform: translateY(-50%);
  background: #fff;
  box-shadow: 0 0 14px 4px var(--astro-secondary), 0 0 24px 6px var(--astro-primary);
}

.astro-meteor-a {
  top: 12%;
  left: 30%;
  animation: astro-meteor-glide 5.8s ease-out infinite 0.6s;
}

.astro-meteor-b {
  top: 48%;
  left: 14%;
  width: 176px;
  animation: astro-meteor-glide 8.4s ease-out infinite 3s;
}

.astro-meteor-c {
  top: 22%;
  left: 58%;
  width: 158px;
  animation: astro-meteor-glide 11.4s ease-out infinite 5.8s;
}

@keyframes astro-spin-cw {
  from { transform: translate3d(-50%, -50%, 0) rotate(0deg); }
  to { transform: translate3d(-50%, -50%, 0) rotate(360deg); }
}

@keyframes astro-spin-ccw {
  from { transform: translate3d(-50%, -50%, 0) rotate(360deg); }
  to { transform: translate3d(-50%, -50%, 0) rotate(0deg); }
}

@keyframes astro-star-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.22; }
}

@keyframes astro-core-breathe {
  0%, 100% { opacity: 1; transform: translate3d(-50%, -50%, 0) scale(1); }
  50% { opacity: 0.72; transform: translate3d(-50%, -50%, 0) scale(1.12); }
}

@keyframes astro-lunar-bob {
  0%, 100% { transform: translate3d(-50%, -50%, 0); }
  50% { transform: translate3d(-50%, calc(-50% - 14px), 0); }
}

@keyframes astro-band-breathe {
  0%, 100% { opacity: 0.98; transform: translate3d(-50%, -50%, 0) rotate(-24deg) scale(1); }
  50% { opacity: 0.68; transform: translate3d(-47%, -53%, 0) rotate(-21deg) scale(1.06); }
}

@keyframes astro-nebula-drift {
  0%, 100% { transform: translate3d(0, 0, 0) scale(1); opacity: 1; }
  50% { transform: translate3d(-44px, 30px, 0) scale(1.13); opacity: 0.72; }
}

@keyframes astro-meteor-glide {
  0% {
    opacity: 0;
    transform: translate3d(-80px, -36px, 0) rotate(22deg) scaleX(0.35);
  }
  5% {
    opacity: var(--astro-meteor-alpha);
    transform: translate3d(68px, 28px, 0) rotate(22deg) scaleX(1);
  }
  18% {
    opacity: 0;
    transform: translate3d(420px, 174px, 0) rotate(22deg) scaleX(0.8);
  }
  100% {
    opacity: 0;
    transform: translate3d(420px, 174px, 0) rotate(22deg) scaleX(0.8);
  }
}

/* Keep full-screen visual coverage on phones while avoiding oversized off-screen GPU textures at 3x DPR */
@media (max-width: 680px) {
  .astro-galactic-band {
    width: 132vmax;
    height: 44vmax;
  }
  .astro-nebula-a {
    top: -18vw;
    right: -12vw;
    width: 120vw;
    height: 105vw;
  }
  .astro-nebula-b {
    bottom: -20vw;
    left: -14vw;
    width: 124vw;
    height: 105vw;
  }
  .astro-nebula-c {
    top: 24%;
    left: 16%;
    width: 104vw;
    height: 92vw;
  }
}

.astro-backdrop.no-ambient .astro-nebula,
.astro-backdrop.no-ambient .astro-galactic-band {
  display: none;
}

.astro-backdrop.is-static .astro-galactic-band,
.astro-backdrop.is-static .astro-nebula,
.astro-backdrop.is-static .astro-star-layer,
.astro-backdrop.is-static .astro-sprite,
.astro-backdrop.is-static .astro-moon-spin {
  animation: none;
  will-change: auto;
}

.astro-backdrop.is-static .astro-meteor {
  display: none;
  will-change: auto;
}

@media (prefers-reduced-motion: reduce) {
  .astro-galactic-band,
  .astro-nebula,
  .astro-star-layer,
  .astro-sprite,
  .astro-moon-spin {
    animation: none;
    will-change: auto;
  }
  .astro-meteor {
    display: none;
    will-change: auto;
  }
}
</style>
