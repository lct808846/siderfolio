<script setup lang="ts">
import { computed, nextTick, onMounted, ref } from 'vue'
import { providersApi, type ModelProvider, type ProviderCatalog, type ProviderDraft, type ProviderModel, type ProviderProtocol } from '../api/model-providers'
import { useModels } from '../stores/models'
import StatusNotice from './StatusNotice.vue'
import SuccessToast from './SuccessToast.vue'
import SettingsSelect from './SettingsSelect.vue'

const emit = defineEmits<{ changed: [] }>()
const models = useModels()
const catalog = ref<ProviderCatalog | null>(null), busy = ref(false), loading = ref(false)
const error = ref(''), message = ref(''), editing = ref(false), deleting = ref<ModelProvider | null>(null)
const editor = ref<HTMLDialogElement | null>(null), picker = ref<HTMLDialogElement | null>(null)
const deleteDialog = ref<HTMLDialogElement | null>(null)
const apiKey = ref(''), storedKey = ref(false)
// API tokens are not login passwords. Mask a normal text control in supported browsers.
const keyInputType = typeof CSS !== 'undefined' && CSS.supports('-webkit-text-security', 'disc') ? 'text' : 'password'
const candidates = ref<ProviderModel[]>([]), selected = ref<string[]>([]), search = ref('')
const directoryTruncated = ref(false)
const form = ref<ProviderDraft>(emptyDraft())
const protocols: readonly { value: ProviderProtocol; label: string; description: string }[] = [
  { value: 'openai_chat', label: 'OpenAI Chat Completions', description: 'DeepSeek、Qwen 与多数兼容网关' },
  { value: 'openai_responses', label: 'OpenAI Responses', description: '使用 /responses 的 OpenAI 服务或兼容网关' },
  { value: 'anthropic', label: 'Anthropic Messages', description: 'Claude 原生 Messages API' },
  { value: 'gemini', label: 'Google Gemini', description: 'Google AI Studio 原生 generateContent API' },
]
const thinkingOptions = [
  { value: 'none', label: '不发送思考参数', description: '通用兼容设置' },
  { value: 'thinking', label: 'thinking', description: '通过 thinking 参数关闭思考' },
  { value: 'enable_thinking', label: 'enable_thinking', description: '通过 enable_thinking 参数关闭思考' },
] as const
const protocolName = (value: ProviderProtocol) => protocols.find(item => item.value === value)?.label || value
const addressExample = computed(() => form.value.protocol === 'gemini' ? 'https://generativelanguage.googleapis.com/v1beta' : form.value.protocol === 'anthropic' ? 'https://api.anthropic.com/v1' : 'https://api.example.com/v1')
function emptyDraft(): ProviderDraft {
  return { revision: 0, id: 'provider-' + crypto.randomUUID().slice(0, 8), name: '', base_url: '', protocol: 'openai_chat', enabled: true, thinking_parameter: 'none', models: [] }
}
const filteredModels = computed(() => candidates.value.filter(model => (model.id + ' ' + model.label).toLowerCase().includes(search.value.trim().toLowerCase())))
async function load() {
  if (loading.value) return
  loading.value = true; error.value = ''
  try { catalog.value = await providersApi.list() }
  catch (e) { error.value = e instanceof Error ? e.message : '服务商列表读取失败。' }
  finally { loading.value = false }
}
async function changed(value: ProviderCatalog, text: string) {
  catalog.value = value; message.value = text
  await models.load(true)
  emit('changed')
}
async function run(task: () => Promise<void>) {
  if (busy.value) return
  busy.value = true; error.value = ''
  try { await task() }
  catch (e) { error.value = e instanceof Error ? e.message : '模型服务操作未完成。' }
  finally { busy.value = false }
}
async function edit(provider?: ModelProvider) {
  if (busy.value || !catalog.value) return
  error.value = ''; apiKey.value = ''; editing.value = !!provider; storedKey.value = !!provider?.key_configured
  form.value = provider ? {
    revision: catalog.value.revision, id: provider.id, name: provider.name, base_url: provider.base_url,
    protocol: provider.protocol, enabled: provider.enabled, thinking_parameter: provider.thinking_parameter,
    models: provider.models.map(model => ({ id: model.id, label: model.label })),
  } : { ...emptyDraft(), revision: catalog.value.revision }
  await nextTick(); editor.value?.showModal()
}
function payload(discover = false): ProviderDraft {
  return { ...form.value, name: form.value.name.trim(), base_url: form.value.base_url.trim(),
    models: discover ? [] : form.value.models.map(model => ({ id: model.id.trim(), label: model.label.trim() || model.id.trim() })),
    thinking_parameter: form.value.protocol === 'openai_chat' ? form.value.thinking_parameter : 'none',
    ...(apiKey.value ? { api_key: apiKey.value } : {}),
  }
}
function save() {
  const draft = payload()
  if (!draft.base_url.startsWith('https://') || /\/(chat\/completions|responses|messages|models)\/?$/.test(draft.base_url) || draft.base_url.includes(':generateContent')) {
    error.value = '请填写 HTTPS API 根地址，不包含具体请求端点。'; return
  }
  if (draft.models.some(model => !/^[A-Za-z0-9][A-Za-z0-9._:/-]*$/.test(model.id))) {
    error.value = '请核对模型 ID，使用服务商提供的英文、数字与 . _ : / - 标识。'; return
  }
  if (new Set(draft.models.map(model => model.id)).size !== draft.models.length) {
    error.value = '同一个服务商的模型 ID 不能重复。'; return
  }
  void run(async () => {
    const value = await providersApi.save(payload())
    editor.value?.close(); apiKey.value = ''
    await changed(value, '模型服务商已保存。')
  })
}
function discover() {
  if (!form.value.name.trim() || !form.value.base_url.trim() || (!apiKey.value && !storedKey.value)) {
    error.value = '请先填写服务商名称、API 地址和密钥。'; return
  }
  void run(async () => {
    const response = await providersApi.discover(payload(true))
    directoryTruncated.value = response.truncated
    const merged = new Map(response.models.map(model => [model.id, model]))
    for (const model of form.value.models) if (model.id.trim()) merged.set(model.id, { ...model })
    candidates.value = [...merged.values()]
    selected.value = form.value.models.filter(model => model.id.trim()).map(model => model.id)
    search.value = ''
    await nextTick(); picker.value?.showModal()
  })
}
function applyModels() {
  if (selected.value.length > 32) { error.value = '每个服务商最多选择 32 个模型。'; picker.value?.close(); return }
  form.value.models = candidates.value.filter(model => selected.value.includes(model.id)).map(model => ({ id: model.id, label: model.label }))
  picker.value?.close()
}
function selectFiltered() {
  const chosen = new Set(selected.value)
  const all = filteredModels.value.every(model => chosen.has(model.id))
  for (const model of filteredModels.value) { if (all) chosen.delete(model.id); else chosen.add(model.id) }
  if (chosen.size > 32) { error.value = '每个服务商最多选择 32 个模型，请缩小搜索范围。'; picker.value?.close(); return }
  selected.value = [...chosen]
}
function setDefault(model: ProviderModel) {
  if (!catalog.value || !model.selection_id) return
  void run(async () => { await changed(await providersApi.defaultModel(model.selection_id!, catalog.value!.revision), '默认模型已更新。') })
}
function confirmDelete(provider: ModelProvider) {
  if (busy.value) return
  deleting.value = provider; error.value = ''; deleteDialog.value?.showModal()
}
function remove() {
  if (!deleting.value || !catalog.value) return
  void run(async () => {
    const value = await providersApi.remove(deleting.value!.id, catalog.value!.revision)
    deleteDialog.value?.close(); deleting.value = null
    await changed(value, '模型服务商已移除。')
  })
}
onMounted(() => { void load() })
</script>

<template>
  <div class="model-providers-settings">
    <SuccessToast v-model:message="message" />
    <StatusNotice v-if="error && !editor?.open && !deleteDialog?.open" title="模型服务操作未完成" :message="error" />
    <p class="settings-footnote">配置模型服务，供查询、科研绘图与文献问答使用。选择与服务商对应的 API 协议，密钥加密保存在服务端。</p>
    <div class="provider-section-heading"><h3>模型服务商</h3></div>
    <p v-if="loading" role="status">正在读取服务商…</p>
    <template v-else-if="catalog">
      <article v-for="provider in catalog.providers" :key="provider.id" class="provider-card">
        <header class="provider-card-heading">
          <div>
            <h4>{{ provider.name }}</h4>
            <div class="ui-pill-list">
              <span class="ui-pill" :class="provider.enabled && provider.key_configured ? 'ui-pill-success' : 'ui-pill-warning'"><span class="ui-dot" aria-hidden="true" />{{ !provider.enabled ? '已停用' : provider.key_configured ? '已配置' : '待配置密钥' }}</span>
              <span class="ui-pill ui-pill-ads">{{ protocolName(provider.protocol) }}</span>
              <span class="ui-pill ui-pill-neutral">{{ provider.models.length }} 个模型</span>
            </div>
          </div>
          <div class="provider-actions"><button type="button" :disabled="busy" @click="edit(provider)">编辑</button><button type="button" :disabled="busy" @click="confirmDelete(provider)">删除</button></div>
        </header>
        <p class="provider-address"><span class="ui-pill ui-pill-mono">{{ provider.base_url }}</span></p>
        <details class="provider-models" :open="catalog.providers.length === 1">
          <summary>已选模型清单（{{ provider.models.length }}）</summary>
          <div v-for="model in provider.models" :key="model.id" class="settings-row"><div><h4>{{ model.label }}</h4><p v-if="model.id !== model.label">{{ model.id }}</p></div><span v-if="model.selection_id === catalog.default_model" class="ui-pill ui-pill-accent"><span class="ui-dot" aria-hidden="true" />默认模型</span><button v-else type="button" :disabled="busy || !provider.enabled || !provider.key_configured" @click="setDefault(model)">设为默认</button></div>
          <p v-if="!provider.models.length" class="settings-footnote">还未选择模型，编辑服务商后获取目录或手动添加。</p>
        </details>
      </article>
      <p v-if="!catalog.providers.length" class="settings-footnote">尚未添加服务商。添加并选择模型后，即可在工作台使用。</p>
      <button type="button" class="provider-add-button" :disabled="busy || catalog.providers.length >= 16" @click="edit()">＋ 添加模型服务商</button>
    </template>
    <p class="settings-footnote">“已配置”仅表示配置已保存。获取模型目录由你手动触发，不等于模型的工具调用或科研回答质量已通过验收。</p>

    <dialog ref="editor" class="project-dialog provider-dialog" aria-labelledby="provider-edit-title" @close="apiKey = ''" @cancel="busy && $event.preventDefault()">
      <header class="provider-dialog-heading"><h2 id="provider-edit-title">{{ editing ? '编辑模型服务商' : '添加模型服务商' }}</h2><button type="button" class="provider-close" aria-label="关闭服务商编辑" :disabled="busy" @click="editor?.close()">×</button></header>
      <StatusNotice v-if="error" title="请检查服务商设置" :message="error" />
      <form class="provider-form" autocomplete="off" @submit.prevent="save">
        <label>显示名称<input v-model="form.name" maxlength="60" required placeholder="例如：我的模型服务" :disabled="busy" /></label>
        <div class="provider-field"><span>API 协议</span><SettingsSelect v-model="form.protocol" label="API 协议" :options="protocols" :disabled="busy" /></div>
        <label>API 地址<input v-model="form.base_url" type="url" maxlength="500" required :placeholder="addressExample" :disabled="busy" /></label>
        <p class="settings-footnote">根地址示例：{{ addressExample }}。不包含具体请求端点。科研查询及绘图要求模型支持工具调用，本地助手仍使用独立配置。</p>
        <label>API 密钥<input v-model="apiKey" class="provider-api-key" name="provider-api-token" :type="keyInputType" autocomplete="off" autocapitalize="off" autocorrect="off" :spellcheck="false" data-lpignore="true" data-1p-ignore data-form-type="other" maxlength="4096" :required="!storedKey" :placeholder="storedKey ? '已配置，留空保留；更改地址或协议需重新填写' : '输入此服务商的 API 密钥'" :disabled="busy" /></label>
        <label class="provider-enabled settings-row settings-switch-row"><span>启用此服务商</span><input v-model="form.enabled" class="settings-switch" type="checkbox" role="switch" :disabled="busy" /></label>
        <details class="provider-advanced"><summary>高级设置</summary><label>服务商标识<input v-model="form.id" pattern="[a-z][a-z0-9-]{0,23}" maxlength="24" :disabled="editing || busy" required /></label><div v-if="form.protocol === 'openai_chat'" class="provider-field"><span>思考参数</span><SettingsSelect v-model="form.thinking_parameter" label="思考参数" :options="thinkingOptions" :disabled="busy" /></div></details>
        <section class="provider-model-editor">
<div class="provider-section-heading"><h3>模型目录</h3><button type="button" :disabled="busy" @click="discover">{{ busy ? '正在处理…' : '获取可用模型' }}</button></div>
          <p v-if="!form.models.length" class="settings-footnote">获取目录后勾选要使用的模型，也可手动填写服务商提供的模型 ID。</p>
          <div v-for="(model, index) in form.models" :key="index" class="provider-model-fields"><label>模型 ID<input v-model="model.id" maxlength="128" required :disabled="busy" /></label><label>显示名称<input v-model="model.label" maxlength="80" :disabled="busy" /></label><button type="button" :disabled="busy" aria-label="移除此模型" @click="form.models.splice(index, 1)">移除</button></div>
          <button type="button" :disabled="busy || form.models.length >= 32" @click="form.models.push({ id: '', label: '' })">＋ 手动添加模型</button>
        </section>
        <div class="project-actions"><button type="button" :disabled="busy" @click="editor?.close()">取消</button><button class="button-primary" :disabled="busy">{{ busy ? '正在处理…' : '保存服务商' }}</button></div>
      </form>
    </dialog>
    <dialog ref="picker" class="project-dialog provider-picker" aria-labelledby="provider-picker-title">
      <header class="provider-dialog-heading"><h2 id="provider-picker-title">选择模型</h2><button type="button" class="provider-close" aria-label="关闭模型选择" @click="picker?.close()">×</button></header>
      <p>勾选后加入此服务商的模型列表，最多 32 个。</p>
      <p v-if="directoryTruncated" class="settings-footnote">服务商目录尚有更多模型，本次仅显示已获取的部分；找不到的模型可返回手动添加。</p>
      <div class="provider-picker-search"><label>搜索模型<input v-model="search" type="search" placeholder="模型名称或 ID" /></label><button type="button" @click="selectFiltered">全选 / 取消</button></div>
      <div class="provider-picker-list"><label v-for="model in filteredModels" :key="model.id"><input v-model="selected" type="checkbox" :value="model.id" /><span>{{ model.id }}</span></label><p v-if="!filteredModels.length" class="settings-footnote">没有匹配模型，可返回手动添加。</p></div>
      <div class="project-actions"><span class="settings-footnote">已选 {{ selected.length }} / 32</span><button type="button" @click="picker?.close()">取消</button><button type="button" class="button-primary" @click="applyModels">更新列表</button></div>
    </dialog>
    <dialog ref="deleteDialog" class="project-dialog provider-auth-dialog" aria-labelledby="provider-delete-title" @cancel="busy && $event.preventDefault()">
      <h2 id="provider-delete-title">删除 {{ deleting?.name }}？</h2><p>将移除此服务商和它的可选模型，已有会话与科研记录保留。默认模型被移除时会选择下一个已启用模型。</p>
      <StatusNotice v-if="error" title="删除未完成" :message="error" />
      <div class="project-actions"><button type="button" :disabled="busy" @click="deleteDialog?.close()">取消</button><button type="button" class="button-danger" :disabled="busy" @click="remove">删除服务商</button></div>
    </dialog>
  </div>
</template>
