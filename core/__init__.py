# -*- coding: utf-8 -*-
"""pixcelOE-TOOL 核心算法包。

模块划分：
    palette    调色板加载、档位推导（含 levels 收窄）
    algorithm  算法本体：去饱和 + 色调分离 + 轮廓扩展 + 对比度感知降采样 + 量化
    pipeline   把上面几步串成一次转换，并缓存可复用的中间结果
    validate   交付验收（复刻 validate_asset.py 的机械硬性检查）
"""
