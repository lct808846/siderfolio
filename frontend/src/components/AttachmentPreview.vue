<script setup lang="ts">
import { nextTick, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import type { ChatAttachment } from '../types'

defineProps<{ attachment: ChatAttachment }>()
const route = useRoute(), dialog = ref<HTMLDialogElement | null>(null)
async function open() { await nextTick(); dialog.value?.showModal() }
watch(() => route.fullPath, () => dialog.value?.close())
</script>

<template>
  <button class="attachment-file" type="button" :aria-label="`查看附件文本：${attachment.filename}`" @click="open"><svg viewBox="0 0 24 24" aria-hidden="true"><path d="M14 3H6a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V9l-6-6Zm0 0v6h6M8 13h8m-8 4h5" /></svg><span><b>{{ attachment.filename }}</b><small>{{ attachment.truncated ? '部分内容 · ' : '' }}{{ attachment.text.length.toLocaleString() }} 字符 · 查看文本</small></span></button>
  <Teleport to="body"><dialog ref="dialog" class="attachment-preview-dialog"><header><div><h2>{{ attachment.filename }}</h2><p>本次发送给模型的附件文本</p></div><button type="button" aria-label="关闭附件预览" @click="dialog?.close()">×</button></header><div class="attachment-preview-content"><p v-for="warning in attachment.warnings" :key="warning" class="notice">{{ warning }}</p><pre>{{ attachment.text }}</pre></div><footer><span>会话保留此文本快照，原文件不会作为知识库文档归档。</span><button type="button" @click="dialog?.close()">关闭</button></footer></dialog></Teleport>
</template>
