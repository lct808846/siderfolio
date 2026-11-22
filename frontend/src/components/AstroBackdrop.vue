<script setup lang="ts">
import { useAppearance } from '../stores/appearance'

const appearance = useAppearance()

const fieldStars = [
  { x: 124, y: 152, r: 1.8, d: '3.6s', delay: '-0.8s', tone: 'primary' },
  { x: 218, y: 266, r: 1.5, d: '4.8s', delay: '-2.1s', tone: 'secondary' },
  { x: 288, y: 118, r: 2.1, d: '4.1s', delay: '-1.3s', tone: 'tertiary' },
  { x: 454, y: 102, r: 1.6, d: '5.2s', delay: '-3.4s', tone: 'primary' },
  { x: 562, y: 248, r: 1.5, d: '3.9s', delay: '-0.5s', tone: 'secondary' },
  { x: 658, y: 128, r: 2.0, d: '4.6s', delay: '-2.7s', tone: 'primary' },
  { x: 742, y: 196, r: 1.4, d: '5.5s', delay: '-1.9s', tone: 'tertiary' },
  { x: 836, y: 106, r: 1.9, d: '3.8s', delay: '-0.4s', tone: 'secondary' },
  { x: 938, y: 168, r: 1.6, d: '4.9s', delay: '-3.1s', tone: 'primary' },
  { x: 1016, y: 92, r: 1.4, d: '5.7s', delay: '-2.2s', tone: 'tertiary' },
  { x: 1474, y: 148, r: 2.0, d: '4.2s', delay: '-1.1s', tone: 'secondary' },
  { x: 1518, y: 294, r: 1.6, d: '5.1s', delay: '-3.8s', tone: 'primary' },
  { x: 1456, y: 462, r: 2.2, d: '3.5s', delay: '-0.9s', tone: 'tertiary' },
  { x: 1362, y: 558, r: 1.5, d: '4.7s', delay: '-2.5s', tone: 'primary' },
  { x: 1528, y: 632, r: 1.8, d: '4.0s', delay: '-1.6s', tone: 'secondary' },
  { x: 1482, y: 842, r: 1.5, d: '5.4s', delay: '-3.2s', tone: 'primary' },
  { x: 1214, y: 882, r: 1.9, d: '4.3s', delay: '-0.7s', tone: 'tertiary' },
  { x: 982, y: 816, r: 1.6, d: '5.0s', delay: '-2.8s', tone: 'secondary' },
  { x: 868, y: 888, r: 2.0, d: '3.7s', delay: '-1.4s', tone: 'primary' },
  { x: 744, y: 786, r: 1.4, d: '5.6s', delay: '-3.9s', tone: 'primary' },
  { x: 642, y: 864, r: 1.8, d: '4.4s', delay: '-0.6s', tone: 'secondary' },
  { x: 526, y: 726, r: 1.5, d: '4.9s', delay: '-2.3s', tone: 'tertiary' },
  { x: 438, y: 638, r: 1.7, d: '3.9s', delay: '-1.7s', tone: 'primary' },
  { x: 172, y: 424, r: 1.9, d: '4.5s', delay: '-3.0s', tone: 'secondary' },
  { x: 256, y: 492, r: 1.4, d: '5.3s', delay: '-0.3s', tone: 'primary' },
  { x: 136, y: 622, r: 1.8, d: '4.1s', delay: '-2.4s', tone: 'tertiary' },
  { x: 356, y: 382, r: 1.5, d: '4.8s', delay: '-1.2s', tone: 'primary' },
  { x: 964, y: 522, r: 1.5, d: '5.1s', delay: '-3.6s', tone: 'secondary' },
  { x: 1094, y: 584, r: 1.7, d: '4.0s', delay: '-1.8s', tone: 'tertiary' },
  { x: 696, y: 642, r: 1.4, d: '5.4s', delay: '-2.9s', tone: 'primary' },
] as const

const cassiopeia = [
  { x: 358, y: 178, r: 2.8, spark: false, d: '4.2s', delay: '-0.5s' },
  { x: 422, y: 230, r: 3.4, spark: true, d: '3.4s', delay: '-1.8s' },
  { x: 486, y: 196, r: 2.6, spark: false, d: '4.9s', delay: '-2.7s' },
  { x: 544, y: 252, r: 3.1, spark: false, d: '3.9s', delay: '-0.9s' },
  { x: 616, y: 204, r: 2.7, spark: true, d: '4.5s', delay: '-3.1s' },
] as const

const bigDipper = [
  { x: 1036, y: 746, r: 2.7, spark: false, d: '4.6s', delay: '-1.1s' },
  { x: 1108, y: 714, r: 3.0, spark: false, d: '3.8s', delay: '-2.4s' },
  { x: 1178, y: 726, r: 2.8, spark: false, d: '5.1s', delay: '-0.6s' },
  { x: 1244, y: 758, r: 3.2, spark: true, d: '3.5s', delay: '-1.9s' },
  { x: 1264, y: 822, r: 2.6, spark: false, d: '4.4s', delay: '-3.2s' },
  { x: 1364, y: 806, r: 3.0, spark: false, d: '4.0s', delay: '-0.8s' },
  { x: 1352, y: 732, r: 3.4, spark: true, d: '3.3s', delay: '-2.1s' },
] as const

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

    <svg class="astro-sky" viewBox="0 0 1600 960" fill="none" preserveAspectRatio="xMidYMid slice">
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
        <linearGradient id="astro-wake-grad" x1="0%" y1="0%" x2="100%" y2="100%">
          <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
          <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0.9" />
        </linearGradient>
        <radialGradient id="astro-sun-corona" cx="50%" cy="50%" r="50%">
          <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
          <stop offset="32%" style="stop-color: var(--astro-primary); stop-opacity: 0.48" />
          <stop offset="68%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.18" />
          <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
        </radialGradient>
        <radialGradient id="astro-horizon-glow" cx="50%" cy="50%" r="50%">
          <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.36" />
          <stop offset="52%" style="stop-color: var(--astro-primary); stop-opacity: 0.16" />
          <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
        </radialGradient>
        <radialGradient id="astro-node-halo-primary" cx="50%" cy="50%" r="50%">
          <stop offset="0%" style="stop-color: var(--astro-primary); stop-opacity: 0.88" />
          <stop offset="48%" style="stop-color: var(--astro-primary); stop-opacity: 0.32" />
          <stop offset="100%" style="stop-color: var(--astro-primary); stop-opacity: 0" />
        </radialGradient>
        <radialGradient id="astro-node-halo-secondary" cx="50%" cy="50%" r="50%">
          <stop offset="0%" style="stop-color: var(--astro-secondary); stop-opacity: 0.92" />
          <stop offset="48%" style="stop-color: var(--astro-secondary); stop-opacity: 0.34" />
          <stop offset="100%" style="stop-color: var(--astro-secondary); stop-opacity: 0" />
        </radialGradient>
        <radialGradient id="astro-node-halo-tertiary" cx="50%" cy="50%" r="50%">
          <stop offset="0%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.88" />
          <stop offset="50%" style="stop-color: var(--astro-tertiary); stop-opacity: 0.3" />
          <stop offset="100%" style="stop-color: var(--astro-tertiary); stop-opacity: 0" />
        </radialGradient>
      </defs>

      <!-- Grand Keplerian Orrery & Astrolabe (Upper-Right / Mid-Right) -->
      <g class="astro-geometry" transform="translate(1228 272)">
        <!-- Outer astrolabe dial & 30-degree ticks -->
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

        <!-- Central luminous star core -->
        <g class="astro-core-pulse">
          <circle r="48" fill="url(#astro-sun-corona)" />
          <circle r="11" class="astro-ring-fine" />
          <path d="M 0 -13 L 2.4 -2.4 L 13 0 L 2.4 2.4 L 0 13 L -2.4 2.4 L -13 0 L -2.4 -2.4 Z" class="astro-star-secondary" />
          <circle r="4.2" class="astro-star-primary" />
        </g>

        <!-- Fast inner planet with curved luminous wake -->
        <g class="astro-orbit-fast">
          <path d="M 0 -96 A 96 96 0 0 1 96 0" stroke="url(#astro-wake-grad)" stroke-width="2" stroke-linecap="round" />
          <circle cx="96" cy="0" r="16" fill="url(#astro-node-halo-primary)" />
          <circle cx="96" cy="0" r="4.2" class="astro-star-primary" />
        </g>

        <!-- Mid-orbit ringed Saturn-like planet (CCW) -->
        <g class="astro-orbit-mid">
          <path d="M 124 -120 A 172 172 0 0 1 172 0" class="astro-arc-secondary" />
          <g transform="translate(172 0)">
            <circle r="20" fill="url(#astro-node-halo-secondary)" />
            <ellipse rx="14" ry="4.5" transform="rotate(-26)" class="astro-planet-ring" />
            <circle r="5.2" class="astro-star-secondary" />
            <path d="M -11 5 A 14 4.5 -26 0 0 11 -5" class="astro-planet-ring-front" />
          </g>
        </g>

        <!-- Outer comet/moon system (CW) -->
        <g class="astro-orbit-slow">
          <path d="M -216 -140 A 258 258 0 0 0 -258 0" class="astro-arc-tertiary" />
          <g transform="translate(-258 0)">
            <circle r="18" fill="url(#astro-node-halo-tertiary)" />
            <circle r="4.4" class="astro-star-tertiary" />
            <circle r="13" class="astro-ring-inner" />
            <g class="astro-moon-spin">
              <circle cx="13" cy="0" r="2.1" class="astro-star-primary" />
            </g>
          </g>
        </g>
      </g>

      <!-- Lower-Left Eclipse Horizon Limb & Celestial Meridian Arcs -->
      <g class="astro-geometry" transform="translate(310 856)">
        <ellipse rx="460" ry="205" transform="rotate(-9)" fill="url(#astro-horizon-glow)" />
        <ellipse rx="476" ry="214" transform="rotate(-9)" stroke="url(#astro-horizon-grad)" stroke-width="1.8" />
        <ellipse rx="418" ry="184" transform="rotate(-9)" class="astro-ring-dashed" />
        <circle r="326" class="astro-ring-fine" stroke-dasharray="4 10" />
        <g class="astro-orbit-horizon">
          <path d="M -118 -304 A 326 326 0 0 1 0 -326" class="astro-arc-secondary" />
          <circle cx="0" cy="-326" r="18" fill="url(#astro-node-halo-secondary)" />
          <circle cx="0" cy="-326" r="4.2" class="astro-star-secondary" />
        </g>
      </g>

      <!-- Mid-Left Minimalist Crescent Moon & Halo -->
      <g class="astro-geometry" transform="translate(292 528)">
        <g class="astro-lunar-float">
          <circle r="34" fill="url(#astro-node-halo-tertiary)" />
          <circle r="24" class="astro-ring-dashed" />
          <path
            d="M 4 -14 A 14.5 14.5 0 1 0 14 7.5 A 11.4 11.4 0 1 1 4 -14 Z"
            class="astro-star-secondary"
          />
        </g>
      </g>

      <!-- Upper-Left Constellation (Cassiopeia W-Asterism) -->
      <g class="astro-constellation">
        <polyline points="358,178 422,230 486,196 544,252 616,204" class="astro-constellation-line" />
        <g
          v-for="star in cassiopeia"
          :key="`cas-${star.x}-${star.y}`"
          class="astro-twinkle"
          :style="{ animationDuration: star.d, animationDelay: star.delay }"
        >
          <circle :cx="star.x" :cy="star.y" :r="star.spark ? 16 : 9" fill="url(#astro-node-halo-primary)" />
          <path
            v-if="star.spark"
            :d="`M ${star.x} ${star.y - 10.5} L ${star.x + 2} ${star.y - 2} L ${star.x + 10.5} ${star.y} L ${star.x + 2} ${star.y + 2} L ${star.x} ${star.y + 10.5} L ${star.x - 2} ${star.y + 2} L ${star.x - 10.5} ${star.y} L ${star.x - 2} ${star.y - 2} Z`"
            class="astro-star-primary"
          />
          <circle v-else :cx="star.x" :cy="star.y" :r="star.r" class="astro-star-primary" />
        </g>
      </g>

      <!-- Lower-Right Constellation (Big Dipper / Ursa Major) -->
      <g class="astro-constellation">
        <polyline
          points="1036,746 1108,714 1178,726 1244,758 1264,822 1364,806 1352,732 1244,758"
          class="astro-constellation-line"
        />
        <g
          v-for="star in bigDipper"
          :key="`dip-${star.x}-${star.y}`"
          class="astro-twinkle"
          :style="{ animationDuration: star.d, animationDelay: star.delay }"
        >
          <circle :cx="star.x" :cy="star.y" :r="star.spark ? 17 : 9.5" fill="url(#astro-node-halo-secondary)" />
          <path
            v-if="star.spark"
            :d="`M ${star.x} ${star.y - 11} L ${star.x + 2.1} ${star.y - 2.1} L ${star.x + 11} ${star.y} L ${star.x + 2.1} ${star.y + 2.1} L ${star.x} ${star.y + 11} L ${star.x - 2.1} ${star.y + 2.1} L ${star.x - 11} ${star.y} L ${star.x - 2.1} ${star.y - 2.1} Z`"
            class="astro-star-secondary"
          />
          <circle v-else :cx="star.x" :cy="star.y" :r="star.r" class="astro-star-primary" />
        </g>
      </g>

      <!-- Multi-Depth Twinkling Starfield -->
      <g class="astro-field-stars">
        <circle
          v-for="star in fieldStars"
          :key="`fs-${star.x}-${star.y}`"
          :cx="star.x"
          :cy="star.y"
          :r="star.r"
          class="astro-twinkle"
          :class="`astro-star-${star.tone}`"
          :style="{ animationDuration: star.d, animationDelay: star.delay }"
        />
      </g>
    </svg>

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
  transform: translate(-50%, -50%) rotate(-24deg);
  background: radial-gradient(
    ellipse 58% 44% at 50% 50%,
    var(--astro-glow-a) 0%,
    var(--astro-glow-b) 42%,
    var(--astro-glow-c) 68%,
    transparent 86%
  );
  opacity: 0.98;
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

.astro-sky {
  position: absolute;
  inset: 0;
  width: 100%;
  height: 100%;
  display: block;
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

.astro-core-pulse {
  transform-origin: 0 0;
  animation: astro-core-breathe 3.8s ease-in-out infinite;
}

.astro-orbit-fast {
  transform-origin: 0 0;
  animation: astro-spin-cw 13s linear infinite;
}

.astro-orbit-mid {
  transform-origin: 0 0;
  animation: astro-spin-ccw 26s linear infinite;
}

.astro-orbit-slow {
  transform-origin: 0 0;
  animation: astro-spin-cw 42s linear infinite;
}

.astro-moon-spin {
  transform-origin: 0 0;
  animation: astro-spin-ccw 5s linear infinite;
}

.astro-orbit-horizon {
  transform-origin: 0 0;
  animation: astro-spin-cw 30s linear infinite;
}

.astro-lunar-float {
  animation: astro-lunar-bob 6s ease-in-out infinite;
}

.astro-twinkle {
  animation: astro-star-breathe 3s ease-in-out infinite;
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
  from { transform: rotate(0deg); }
  to { transform: rotate(360deg); }
}

@keyframes astro-spin-ccw {
  from { transform: rotate(360deg); }
  to { transform: rotate(0deg); }
}

@keyframes astro-star-breathe {
  0%, 100% { opacity: 1; }
  50% { opacity: 0.16; }
}

@keyframes astro-core-breathe {
  0%, 100% { opacity: 1; transform: scale(1); }
  50% { opacity: 0.72; transform: scale(1.12); }
}

@keyframes astro-lunar-bob {
  0%, 100% { transform: translateY(0); }
  50% { transform: translateY(-14px); }
}

@keyframes astro-band-breathe {
  0%, 100% { opacity: 0.98; transform: translate(-50%, -50%) rotate(-24deg) scale(1); }
  50% { opacity: 0.68; transform: translate(-47%, -53%) rotate(-21deg) scale(1.06); }
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

.astro-backdrop.no-ambient .astro-nebula,
.astro-backdrop.no-ambient .astro-galactic-band {
  display: none;
}

.astro-backdrop.is-static .astro-galactic-band,
.astro-backdrop.is-static .astro-nebula,
.astro-backdrop.is-static .astro-core-pulse,
.astro-backdrop.is-static .astro-orbit-fast,
.astro-backdrop.is-static .astro-orbit-mid,
.astro-backdrop.is-static .astro-orbit-slow,
.astro-backdrop.is-static .astro-moon-spin,
.astro-backdrop.is-static .astro-orbit-horizon,
.astro-backdrop.is-static .astro-lunar-float,
.astro-backdrop.is-static .astro-twinkle {
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
  .astro-core-pulse,
  .astro-orbit-fast,
  .astro-orbit-mid,
  .astro-orbit-slow,
  .astro-moon-spin,
  .astro-orbit-horizon,
  .astro-lunar-float,
  .astro-twinkle {
    animation: none;
  }
  .astro-meteor {
    display: none;
  }
}
</style>
