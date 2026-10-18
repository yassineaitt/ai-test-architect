Test: tests/checkout/adoption.spec.ts › submits an adoption request

Failing step:
  await page.locator('#submit-btn').click();

Error:
  TimeoutError: locator.click: Timeout 10000ms exceeded.
  waiting for locator('#submit-btn')

The test passed until the checkout form was migrated to the new design system last sprint.
