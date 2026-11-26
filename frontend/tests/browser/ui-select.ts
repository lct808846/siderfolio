import { expect, type Locator, type Page } from '@playwright/test'

export async function chooseUiOption(
  page: Page,
  trigger: Locator,
  option: string | RegExp | { index: number },
) {
  await trigger.click()
  const listbox = page.getByRole('listbox').last()
  await expect(listbox).toBeVisible()
  if (typeof option === 'object' && 'index' in option) {
    await listbox.getByRole('option').nth(option.index).click()
  } else {
    await listbox.getByRole('option', { name: option }).first().click()
  }
}
