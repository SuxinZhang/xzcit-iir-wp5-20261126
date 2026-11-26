import unittest
from pathlib import Path

DEPLOY = Path(__file__).resolve().parents[1]


class OtaDeploymentContractTest(unittest.TestCase):
    """Static checks for the independent OTA agent deployment contract.
    独立 OTA 代理部署契约的静态检查。
    """

    def test_ota_agent_is_not_part_of_iir_target(self):
        service = (DEPLOY / 'systemd/iir-ota-agent.service').read_text(encoding='utf-8')
        self.assertIn('WantedBy=multi-user.target', service)
        active_lines = [line.strip() for line in service.splitlines()
                        if line.strip() and not line.strip().startswith('#')]
        self.assertFalse(any(line.startswith('PartOf=') for line in active_lines))
        self.assertIn('IIR_OTA_PORT=8090', service)

    def test_caddy_routes_ota_before_web_fallback(self):
        caddy = (DEPLOY / 'Caddyfile').read_text(encoding='utf-8')
        self.assertIn('/api/ota/*', caddy)
        self.assertIn('/ws/ota/*', caddy)
        self.assertIn('127.0.0.1:8090', caddy)
        self.assertIn('max_size 512MB', caddy)

    def test_ota_env_contains_flash_sequencing(self):
        env = (DEPLOY / 'wp5.env.example').read_text(encoding='utf-8')
        self.assertIn('STM32FLASH_INIT_SEQ=', env)
        self.assertIn('STM32FLASH_EXIT_SEQ=', env)
        self.assertIn('IIR_OTA_PACKAGE_DIR=', env)


if __name__ == '__main__':
    unittest.main()
