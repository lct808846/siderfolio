<script setup lang="ts">
defineProps<{ modelValue: string; label: string; options: { value: string; label: string }[] }>()
defineEmits<{ 'update:modelValue': [value: string] }>()
</script>

<template>
  <nav class="panel-switcher" :aria-label="label">
    <button
      v-for="option in options" :key="option.value" type="button"
      :aria-pressed="modelValue === option.value" @click="$emit('update:modelValue', option.value)">
      {{ option.label }}
    </button>
  </nav>
</template>
