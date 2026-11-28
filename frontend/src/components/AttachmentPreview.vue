<script setup lang="ts">
import { computed, nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { ChatAttachment } from '../types'

const props = defineProps<{ attachment: ChatAttachment }>()
const route = useRoute()
const dialog = ref<HTMLDialogElement | null>(null)
const isImage = computed(() => Boolean(props.attachment.media_type?.startsWith('image/') && props.attachment.image_data_url))
const detailSummary = computed(() => {
  if (isImage.value) {
    const dims = props.attachment.image_width && props.attachment.image_height
      ? `${props.attachment.image_width}×${props.attachment.image_height} · `
      : ''
    return `${dims}查看原图`
  }
  return `${props.attachment.truncated ? '部分内容 · ' : ''}${props.attachment.text.length.toLocaleString()} 字符 · 查看文本`
})
async function open() { await nextTick(); dialog.value?.showModal() }
function onBackdropClick(event: MouseEvent) {
  if (event.target === dialog.value) dialog.value?.close()
}
watch(() => route.fullPath, () => dialog.value?.close())
</script>

<template>
  <button
    class="attachment-file"
    :class="{ 'is-image': isImage }"
    type="button"
    :aria-label="isImage ? `查看图片附件：${attachment.filename}` : `查看附件文本：${attachment.filename}`"
    @click="open"
  >
    <img
      v-if="isImage && attachment.image_data_url"
      :src="attachment.image_data_url"
      :alt="attachment.filename"
      class="attachment-thumb"
    />
    <svg v-else viewBox="0 0 24 24" aria-hidden="true">
      <path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8m-8 4h5" />
    </svg>
    <span>
      <b>{{ attachment.filename }}</b>
      <small>{{ detailSummary }}</small>
    </span>
  </button>
  <Teleport to="body">
    <dialog ref="dialog" class="attachment-preview-dialog" @click="onBackdropClick">
      <header>
        <div>
          <h2>{{ attachment.filename }}</h2>
          <p>{{ isImage ? '本次发送给模型的图片附件' : '本次发送给模型的附件文本' }}</p>
        </div>
        <button type="button" aria-label="关闭附件预览" @click="dialog?.close()">×</button>
      </header>
      <div class="attachment-preview-content">
        <p v-for="warning in attachment.warnings" :key="warning" class="notice">{{ warning }}</p>
        <div v-if="isImage && attachment.image_data_url" class="attachment-preview-image-wrap">
          <img :src="attachment.image_data_url" :alt="attachment.filename" class="attachment-preview-image" />
        </div>
        <pre v-else>{{ attachment.text }}</pre>
      </div>
      <footer>
        <span>{{ isImage ? '图片随本轮对话发送给所选模型，不会自动归档为知识库文档。' : '会话保留此文本快照，原文件不会作为知识库文档归档。' }}</span>
        <button type="button" @click="dialog?.close()">关闭</button>
      </footer>
    </dialog>
  </Teleport>
</template>
