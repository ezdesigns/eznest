"""QA-only hosted Windows probe: unchanged consent assertion, synthetic host only."""
import json
import os
from pathlib import Path
import re
import sys
import unittest


def main():
    if not (sys.platform == 'win32' and os.environ.get('GITHUB_ACTIONS') == 'true'
            and os.environ.get('RUNNER_ENVIRONMENT') == 'github-hosted'
            and os.environ.get('GITHUB_REPOSITORY') == 'ezdesigns/eznest'):
        raise RuntimeError('Only a disposable hosted Windows runner may start this browser probe.')
    root = Path(os.environ['RUNNER_TEMP']).resolve(strict=True) / 'rc8-consent-probe'
    root.mkdir(exist_ok=False)
    from playwright.sync_api import Page
    import test_telemetry_consent
    original = Page.wait_for_function

    def observed(page, *args, **kwargs):
        try:
            return original(page, *args, **kwargs)
        except Exception:
            # Capture while the failing page is still alive. No headers, session
            # token, browser storage, trace archive or request body is collected.
            try:
                value = page.evaluate("""() => ({
                  agreeDisabled: document.querySelector('#telemetry-agree')?.disabled,
                  enableDisabled: document.querySelector('#telemetry-enable')?.disabled,
                  configured: typeof outputSharing === 'undefined' ? null : outputSharing?.configured,
                  enabled: typeof outputSharing === 'undefined' ? null : outputSharing?.enabled,
                  paused: typeof outputSharing === 'undefined' ? null : outputSharing?.paused,
                  status: document.querySelector('#telemetry-status')?.textContent?.slice(0,160)
                })""")
                raw = re.sub(r'osa_[A-Za-z0-9_-]+', '[synthetic-token]', json.dumps(value))
                (root / 'failure.json').write_text(raw, encoding='utf-8')
                print('CONSENT_FAILURE_STATE: ' + raw, flush=True)
                page.screenshot(path=str(root / 'synthetic-failure.png'))
            except Exception:
                print('CONSENT_FAILURE_STATE_UNAVAILABLE', flush=True)
            raise

    Page.wait_for_function = observed
    try:
        suite = unittest.defaultTestLoader.loadTestsFromModule(test_telemetry_consent)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
    finally:
        Page.wait_for_function = original
    (root / 'result.json').write_text(json.dumps({'tests':result.testsRun,
        'successful':result.wasSuccessful(), 'errors':len(result.errors),
        'failures':len(result.failures)}), encoding='utf-8')
    return 0 if result.wasSuccessful() else 1


if __name__ == '__main__':
    raise SystemExit(main())
