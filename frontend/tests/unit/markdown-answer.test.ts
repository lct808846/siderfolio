import { expect, it } from 'vitest'
import { mount } from '@vue/test-utils'
import MarkdownAnswer from '../../src/components/MarkdownAnswer'

it('renders headings, emphasis, lists and wide tables while retaining numeric identifiers', () => {
  const wrapper = mount(MarkdownAnswer, { props: { text: '# 查询结果\n\n**位置候选源**\n\n- 不代表成员\n\n| source_id | RA |\n| --- | ---: |\n| 5853498713190525696 | 56.74710 |' } })
  expect(wrapper.find('h1').text()).toBe('查询结果')
  expect(wrapper.find('strong').text()).toBe('位置候选源')
  expect(wrapper.find('li').text()).toBe('不代表成员')
  expect(wrapper.find('[role="region"] table').exists()).toBe(true)
  expect(wrapper.find('td').text()).toBe('5853498713190525696')
})

it('does not create model-provided HTML, scripts, images or unsafe links', () => {
  const wrapper = mount(MarkdownAnswer, { props: { text: '<script>alert(1)</script>\n\n<img src=x onerror=alert(1)>\n\n[坏链接](javascript:alert%281%29)\n\n![追踪](https://example.org/track.png)' } })
  expect(wrapper.find('script').exists()).toBe(false)
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a').exists()).toBe(false)
  expect(wrapper.text()).toContain('<script>')
})

it('keeps code literal and adds isolation attributes to clickable external references', () => {
  const wrapper = mount(MarkdownAnswer, { props: { text: '```html\n<img src=x>\n```\n\n[来源](https://example.org/paper)' } })
  expect(wrapper.find('pre code').text()).toContain('<img src=x>')
  expect(wrapper.find('img').exists()).toBe(false)
  expect(wrapper.find('a').attributes('rel')).toBe('noopener noreferrer')
  expect(wrapper.find('a').attributes('referrerpolicy')).toBe('no-referrer')
})
