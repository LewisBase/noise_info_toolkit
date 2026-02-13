# -*- coding: utf-8 -*-
"""
@DATE: 2026-02-13 22:00:00
@Author: Liu Hengjiang
@File: test/test_dose_calculator.py
@Software: vscode
@Description:
        噪声剂量计算器单元测试
"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import unittest
import numpy as np
from app.core.dose_calculator import (
    DoseCalculator, DoseProfile, DoseStandard,
    calculate_noise_dose, calculate_twa_from_dose, get_standard_info
)


class TestDoseProfile(unittest.TestCase):
    """测试 DoseProfile 类"""
    
    def test_profile_creation(self):
        """测试配置对象创建"""
        profile = DoseProfile(
            name="TEST",
            criterion_level=85.0,
            exchange_rate=3.0,
            threshold=0.0,
            reference_duration=8.0
        )
        self.assertEqual(profile.name, "TEST")
        self.assertEqual(profile.criterion_level, 85.0)
        self.assertEqual(profile.exchange_rate, 3.0)
    
    def test_profile_auto_description(self):
        """测试自动生成的描述"""
        profile = DoseProfile(
            name="TEST",
            criterion_level=85.0,
            exchange_rate=3.0
        )
        self.assertIn("TEST", profile.description)
        self.assertIn("85", profile.description)


class TestDoseCalculatorNIOSH(unittest.TestCase):
    """测试 NIOSH 标准计算"""
    
    def setUp(self):
        self.profile = DoseCalculator.get_profile("NIOSH")
    
    def test_niosh_85dba_8h(self):
        """测试 NIOSH: 85 dBA 持续 8 小时 = 100% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(85.0, 8*3600, self.profile)
        self.assertAlmostEqual(dose, 100.0, places=1)
    
    def test_niosh_88dba_8h(self):
        """测试 NIOSH: 88 dBA 持续 8 小时 = 200% 剂量 (3dB翻倍)"""
        dose = DoseCalculator.calculate_dose_increment(88.0, 8*3600, self.profile)
        self.assertAlmostEqual(dose, 200.0, places=1)
    
    def test_niosh_91dba_8h(self):
        """测试 NIOSH: 91 dBA 持续 8 小时 = 400% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(91.0, 8*3600, self.profile)
        self.assertAlmostEqual(dose, 400.0, places=1)
    
    def test_niosh_85dba_4h(self):
        """测试 NIOSH: 85 dBA 持续 4 小时 = 50% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(85.0, 4*3600, self.profile)
        self.assertAlmostEqual(dose, 50.0, places=1)
    
    def test_niosh_95dba_8h(self):
        """测试 NIOSH: 95 dBA 持续 8 小时 (约 10.08 倍 = 1008%)"""
        dose = DoseCalculator.calculate_dose_increment(95.0, 8*3600, self.profile)
        # 95-85=10dB, 10/3=3.33, 2^3.33≈10.08
        expected = 100 * (2 ** (10/3))
        self.assertAlmostEqual(dose, expected, places=1)
    
    def test_niosh_allowed_time_88dba(self):
        """测试 NIOSH: 88 dBA 允许时间 = 4 小时"""
        allowed_time = DoseCalculator.calculate_allowed_time(88.0, self.profile)
        self.assertAlmostEqual(allowed_time, 4.0, places=1)
    
    def test_niosh_allowed_time_91dba(self):
        """测试 NIOSH: 91 dBA 允许时间 = 2 小时"""
        allowed_time = DoseCalculator.calculate_allowed_time(91.0, self.profile)
        self.assertAlmostEqual(allowed_time, 2.0, places=1)
    
    def test_niosh_twa_from_100pct_dose(self):
        """测试 NIOSH: 100% 剂量对应 TWA = 85 dBA"""
        twa = DoseCalculator.calculate_twa(100.0, self.profile)
        self.assertAlmostEqual(twa, 85.0, places=1)
    
    def test_niosh_twa_from_200pct_dose(self):
        """测试 NIOSH: 200% 剂量对应 TWA = 88 dBA"""
        twa = DoseCalculator.calculate_twa(200.0, self.profile)
        self.assertAlmostEqual(twa, 88.0, places=1)
    
    def test_niosh_lex_from_100pct_dose(self):
        """测试 NIOSH: 100% 剂量对应 LEX = 85 dBA"""
        lex = DoseCalculator.calculate_lex(100.0, self.profile)
        self.assertAlmostEqual(lex, 85.0, places=1)


class TestDoseCalculatorOSHA(unittest.TestCase):
    """测试 OSHA 标准计算"""
    
    def setUp(self):
        self.profile_pel = DoseCalculator.get_profile("OSHA_PEL")
        self.profile_hca = DoseCalculator.get_profile("OSHA_HCA")
    
    def test_osha_pel_90dba_8h(self):
        """测试 OSHA_PEL: 90 dBA 持续 8 小时 = 100% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(90.0, 8*3600, self.profile_pel)
        self.assertAlmostEqual(dose, 100.0, places=1)
    
    def test_osha_pel_95dba_8h(self):
        """测试 OSHA_PEL: 95 dBA 持续 8 小时 = 200% 剂量 (5dB翻倍)"""
        dose = DoseCalculator.calculate_dose_increment(95.0, 8*3600, self.profile_pel)
        self.assertAlmostEqual(dose, 200.0, places=1)
    
    def test_osha_pel_100dba_8h(self):
        """测试 OSHA_PEL: 100 dBA 持续 8 小时 = 400% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(100.0, 8*3600, self.profile_pel)
        self.assertAlmostEqual(dose, 400.0, places=1)
    
    def test_osha_hca_85dba_8h(self):
        """测试 OSHA_HCA: 85 dBA 持续 8 小时 = 100% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(85.0, 8*3600, self.profile_hca)
        self.assertAlmostEqual(dose, 100.0, places=1)
    
    def test_osha_pel_allowed_time_95dba(self):
        """测试 OSHA_PEL: 95 dBA 允许时间 = 4 小时"""
        allowed_time = DoseCalculator.calculate_allowed_time(95.0, self.profile_pel)
        self.assertAlmostEqual(allowed_time, 4.0, places=1)
    
    def test_osha_pel_allowed_time_100dba(self):
        """测试 OSHA_PEL: 100 dBA 允许时间 = 2 小时"""
        allowed_time = DoseCalculator.calculate_allowed_time(100.0, self.profile_pel)
        self.assertAlmostEqual(allowed_time, 2.0, places=1)
    
    def test_osha_twa_from_100pct_dose(self):
        """测试 OSHA: 100% 剂量对应 TWA = 90 dBA (PEL)"""
        twa = DoseCalculator.calculate_twa(100.0, self.profile_pel)
        self.assertAlmostEqual(twa, 90.0, places=1)
    
    def test_osha_twa_from_200pct_dose(self):
        """测试 OSHA: 200% 剂量对应 TWA (使用16.61系数)"""
        twa = DoseCalculator.calculate_twa(200.0, self.profile_pel)
        # TWA = 16.61 * log10(2) + 90 ≈ 95
        expected = 16.61 * np.log10(2) + 90
        self.assertAlmostEqual(twa, expected, places=1)


class TestDoseCalculatorEUISO(unittest.TestCase):
    """测试 EU_ISO 标准计算"""
    
    def setUp(self):
        self.profile = DoseCalculator.get_profile("EU_ISO")
    
    def test_eu_iso_85dba_8h(self):
        """测试 EU_ISO: 85 dBA 持续 8 小时 = 100% 剂量"""
        dose = DoseCalculator.calculate_dose_increment(85.0, 8*3600, self.profile)
        self.assertAlmostEqual(dose, 100.0, places=1)
    
    def test_eu_iso_lex_from_100pct_dose(self):
        """测试 EU_ISO: 100% 剂量对应 LEX = 85 dBA"""
        lex = DoseCalculator.calculate_lex(100.0, self.profile)
        self.assertAlmostEqual(lex, 85.0, places=1)


class TestDoseCalculatorEdgeCases(unittest.TestCase):
    """测试边界情况"""
    
    def setUp(self):
        self.profile = DoseCalculator.get_profile("NIOSH")
    
    def test_below_threshold(self):
        """测试低于阈值的声级不计入剂量"""
        profile_with_threshold = DoseProfile(
            name="TEST",
            criterion_level=85.0,
            exchange_rate=3.0,
            threshold=80.0  # 设置80dBA阈值
        )
        dose = DoseCalculator.calculate_dose_increment(75.0, 8*3600, profile_with_threshold)
        self.assertEqual(dose, 0.0)
    
    def test_zero_duration(self):
        """测试零持续时间"""
        dose = DoseCalculator.calculate_dose_increment(85.0, 0, self.profile)
        self.assertEqual(dose, 0.0)
    
    def test_zero_dose_twa(self):
        """测试零剂量的TWA"""
        twa = DoseCalculator.calculate_twa(0.0, self.profile)
        self.assertEqual(twa, 0.0)
    
    def test_negative_dose_twa(self):
        """测试负剂量的TWA"""
        twa = DoseCalculator.calculate_twa(-10.0, self.profile)
        self.assertEqual(twa, 0.0)
    
    def test_very_low_sound_level(self):
        """测试极低声级"""
        dose = DoseCalculator.calculate_dose_increment(30.0, 8*3600, self.profile)
        # 应该是一个很小的值，但不为零（因为没有阈值）
        self.assertGreater(dose, 0.0)
        self.assertLess(dose, 0.01)


class TestDoseCalculatorCumulative(unittest.TestCase):
    """测试累计剂量计算"""
    
    def setUp(self):
        self.profile = DoseCalculator.get_profile("NIOSH")
    
    def test_cumulative_dose_same_level(self):
        """测试相同声级的累计剂量"""
        # 4小时 + 4小时 = 8小时
        measurements = [
            (85.0, 4*3600),
            (85.0, 4*3600)
        ]
        total_dose = DoseCalculator.calculate_total_dose(measurements, self.profile)
        self.assertAlmostEqual(total_dose, 100.0, places=1)
    
    def test_cumulative_dose_different_levels(self):
        """测试不同声级的累计剂量"""
        # 85dBA 4小时 (50%) + 88dBA 4小时 (100%) = 150%
        measurements = [
            (85.0, 4*3600),
            (88.0, 4*3600)
        ]
        total_dose = DoseCalculator.calculate_total_dose(measurements, self.profile)
        self.assertAlmostEqual(total_dose, 150.0, places=1)


class TestConvenienceFunctions(unittest.TestCase):
    """测试便捷函数"""
    
    def test_calculate_noise_dose(self):
        """测试便捷函数 calculate_noise_dose"""
        dose = calculate_noise_dose(85.0, 8.0, "NIOSH")
        self.assertAlmostEqual(dose, 100.0, places=1)
    
    def test_calculate_twa_from_dose(self):
        """测试便捷函数 calculate_twa_from_dose"""
        twa = calculate_twa_from_dose(100.0, "NIOSH")
        self.assertAlmostEqual(twa, 85.0, places=1)
    
    def test_get_standard_info(self):
        """测试便捷函数 get_standard_info"""
        info = get_standard_info("NIOSH")
        self.assertEqual(info["name"], "NIOSH")
        self.assertEqual(info["criterion_level_dBA"], 85.0)
        self.assertEqual(info["exchange_rate_dB"], 3.0)


class TestDoseCalculatorProfiles(unittest.TestCase):
    """测试预定义配置"""
    
    def test_get_all_profiles(self):
        """测试获取所有配置"""
        profiles = DoseCalculator.get_all_profiles()
        self.assertEqual(len(profiles), 4)
        self.assertIn("NIOSH", profiles)
        self.assertIn("OSHA_PEL", profiles)
        self.assertIn("OSHA_HCA", profiles)
        self.assertIn("EU_ISO", profiles)
    
    def test_invalid_standard(self):
        """测试无效标准名称"""
        with self.assertRaises(ValueError):
            DoseCalculator.get_profile("INVALID")


class TestDoseCalculatorMultiStandard(unittest.TestCase):
    """测试多标准同时计算"""
    
    def test_multi_standard_calculation(self):
        """测试同时计算所有标准"""
        results = DoseCalculator.calculate_multi_standard(85.0, 8*3600)
        
        self.assertIn("NIOSH", results)
        self.assertIn("OSHA_PEL", results)
        self.assertIn("OSHA_HCA", results)
        self.assertIn("EU_ISO", results)
        
        # NIOSH 和 EU_ISO 应该相同 (85/3/8)
        self.assertAlmostEqual(
            results["NIOSH"]["dose_pct"],
            results["EU_ISO"]["dose_pct"],
            places=5
        )


class TestLEXCalculation(unittest.TestCase):
    """测试 LEX,8h 计算"""
    
    def test_lex_100pct(self):
        """测试 100% 剂量对应的 LEX"""
        profile = DoseCalculator.get_profile("NIOSH")
        lex = DoseCalculator.calculate_lex(100.0, profile)
        self.assertAlmostEqual(lex, 85.0, places=1)
    
    def test_lex_200pct(self):
        """测试 200% 剂量对应的 LEX"""
        profile = DoseCalculator.get_profile("NIOSH")
        lex = DoseCalculator.calculate_lex(200.0, profile)
        self.assertAlmostEqual(lex, 88.0, places=1)  # 85 + 10*log10(2)
    
    def test_dose_from_lex(self):
        """测试从 LEX 反算剂量"""
        profile = DoseCalculator.get_profile("NIOSH")
        
        # 85 dBA -> 100%
        dose = DoseCalculator.calculate_dose_from_lex(85.0, profile)
        self.assertAlmostEqual(dose, 100.0, places=1)
        
        # 88 dBA -> 200% (允许一定误差)
        dose = DoseCalculator.calculate_dose_from_lex(88.0, profile)
        self.assertAlmostEqual(dose, 200.0, places=0)  # 使用整数精度


def run_tests():
    """运行所有测试"""
    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    
    # 添加所有测试类
    suite.addTests(loader.loadTestsFromTestCase(TestDoseProfile))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorNIOSH))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorOSHA))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorEUISO))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorEdgeCases))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorCumulative))
    suite.addTests(loader.loadTestsFromTestCase(TestConvenienceFunctions))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorProfiles))
    suite.addTests(loader.loadTestsFromTestCase(TestDoseCalculatorMultiStandard))
    suite.addTests(loader.loadTestsFromTestCase(TestLEXCalculation))
    
    runner = unittest.TextTestRunner(verbosity=2)
    result = runner.run(suite)
    
    return result.wasSuccessful()


if __name__ == "__main__":
    success = run_tests()
    sys.exit(0 if success else 1)
