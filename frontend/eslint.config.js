import eslint from '@eslint/js'
import tseslint from 'typescript-eslint'
import vue from 'eslint-plugin-vue'
import globals from 'globals'

export default tseslint.config(
  { ignores: ['dist/**', 'node_modules/**', 'test-results/**', 'playwright-report/**'] },
  eslint.configs.recommended,
  ...tseslint.configs.recommended,
  ...vue.configs['flat/recommended'],
  {
    languageOptions: { globals: { ...globals.browser, ...globals.node }, parserOptions: { parser: tseslint.parser } },
    rules: { 'vue/multi-word-component-names': 'off', 'vue/max-attributes-per-line': 'off', 'vue/html-self-closing': 'off', 'vue/singleline-html-element-content-newline': 'off', 'vue/html-closing-bracket-newline': 'off', 'vue/html-indent': 'off' },
  },
)
