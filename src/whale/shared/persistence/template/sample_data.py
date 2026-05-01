"""全套风电场样本数据生成脚本.

大唐集团 → 华北分公司 → 张北风电场
3 个 IED 采集模板，30 台风机共用风机模板
GB/T 30966.2 全量测点覆盖

Usage: python -m whale.shared.persistence.template.sample_data
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from whale.shared.persistence.init_db import init_db
from whale.shared.persistence.orm import (
    AcquisitionTask,
    AssetAttribute,
    AssetBOM,
    AssetInstance,
    AssetModel,
    AssetType,
    CDCDict,
    ComponentAttribute,
    ComponentInstance,
    ComponentModel,
    ComponentType,
    DO,
    DOState,
    ElectricalTopology,
    FCDict,
    IED,
    LD,
    LN,
    NetworkTopology,
    Organization,
    ScadaDataType,
    StateSnapshotOutbox,
)
from whale.shared.persistence.session import session_scope

TURBINE_COUNT = 30
PLANT_NAME = "张北风电场"
REGION_NAME = "华北分公司"
GROUP_NAME = "大唐集团"

AT_WIND_TURBINE = "风力发电机"
AT_INVERTER = "逆变器"
AT_PV_PANEL = "光伏面板"
AT_PCS = "储能变流器"
AT_BATTERY = "储能系统"
AT_TRANSFORMER = "变压器"
AT_SVG = "SVG无功补偿"
AT_SUBSTATION = "变电站"
AT_SWITCHGEAR = "开关柜"
AT_MET_STATION = "气象站"
AT_CABLE = "电缆"

CT_BLADE, CT_TOWER, CT_GEARBOX, CT_GENERATOR, CT_PITCH = ("叶片", "塔筒", "齿轮箱", "发电机", "变桨系统")
CT_ROTOR, CT_NACELLE, CT_CONVERTER, CT_CONTROL, CT_YAW = ("转子", "机舱", "变流器", "控制系统", "偏航系统")
CT_MAIN_SHAFT, CT_BRAKE, CT_POWER_MODULE, CT_COOLING, CT_CONTROL_BOARD = ("主轴", "制动系统", "电源模块", "散热系统", "控制板")
CT_TRACKER, CT_COMBINER, CT_BATTERY_CELL, CT_BMS, CT_THERMAL = ("跟踪支架", "汇流箱", "电池单体", "电池管理系统", "热管理系统")
CT_TRANSFORMER_COMP, CT_CIRCUIT_BREAKER = ("变压器组件", "断路器")


def generate_all_sample_data() -> None:
    from whale.shared.persistence.template.gbt_30966_fields import ALL_LOGICAL_NODES

    with session_scope() as session:
        print("=" * 60)
        print("  张北风电场全套样本数据生成")
        print("=" * 60)

        group, region, plant = _create_org_hierarchy(session)
        session.flush()
        print(f"✓ 组织: {GROUP_NAME} → {REGION_NAME} → {PLANT_NAME}")

        data_types = _create_scada_data_types(session)
        asset_types = _create_asset_types(session)
        component_types = _create_component_types(session)
        session.flush()
        print(f"✓ 类型: {len(asset_types)} 资产 + {len(component_types)} 部件 + {len(data_types)} 数据类型")

        asset_models = _create_asset_models(session, asset_types)
        component_models = _create_component_models(session, component_types)
        session.flush()
        _create_asset_attributes(session, asset_types, data_types)
        _create_component_attributes(session, component_types, data_types)
        _create_bom(session, asset_types, asset_models, component_types, component_models)
        _create_cdc_fc_dicts(session)
        session.flush()
        model_count = len(asset_models) + len(component_models)
        print(f"✓ 型号: {model_count} 型号 + 属性定义 + BOM + CDC/FC")

        assets = _create_asset_instances(session, asset_types, asset_models, plant)
        session.flush()
        turbines = assets["turbines"]
        print(f"✓ 资产实例: {len(turbines)} 台风机 + 箱变/逆变器/储能/SVG/气象站/光伏")

        _create_component_instances(session, component_types, component_models, turbines)
        session.flush()
        print(f"✓ 部件实例: 每台风机 8 部件 × {TURBINE_COUNT} 台")

        ied, do_count = _create_ied_template(session, ALL_LOGICAL_NODES, "WTG", data_types)
        met_ied, met_do_count = _create_met_ied_template(session, "MET", data_types)
        sub_ied, sub_do_count = _create_substation_ied_template(session, "SUB", data_types)
        session.flush()
        print(f"✓ IED 模板: 3 个, 共 {do_count + met_do_count + sub_do_count} DO")

        tasks = _create_acquisition_tasks(session, turbines, ied, met_ied, sub_ied)
        session.flush()
        print(f"✓ 采集任务: {len(tasks)} 个")

        vs_count = _create_do_states(session)
        outbox_count = _create_outbox_samples(session)
        topo_count = _create_topology(session, assets)
        session.flush()
        print(f"✓ DO 状态: {vs_count} / 发件箱: {outbox_count} / 拓扑: {topo_count}")

        session.commit()

        wide_count = _create_wide_model_views(session)
        print(f"✓ 宽表视图: {wide_count} 个")
        print("\n" + "=" * 60)
        print("  全部样本数据生成完毕")
        print("=" * 60)


# ══════════════════════════════════════════════════════════════════════
# 1. 组织
# ══════════════════════════════════════════════════════════════════════

def _create_org_hierarchy(session: Session) -> tuple[Organization, Organization, Organization]:
    group = Organization(org_name=GROUP_NAME)
    session.add(group); session.flush()
    region = Organization(org_name=REGION_NAME, parent_org_id=group.org_id)
    session.add(region); session.flush()
    plant = Organization(org_name=PLANT_NAME, parent_org_id=region.org_id)
    session.add(plant); session.flush()
    return group, region, plant


# ══════════════════════════════════════════════════════════════════════
# 2. SCADA 数据类型
# ══════════════════════════════════════════════════════════════════════

def _create_scada_data_types(session: Session) -> dict[str, ScadaDataType]:
    types = [
        ("BOOLEAN", "布尔量", "Binary", 1, "0", "1"),
        ("INT8", "有符号8位整数", "Two's complement", 8, "-128", "127"),
        ("INT16", "有符号16位整数", "Two's complement", 16, "-32768", "32767"),
        ("INT32", "有符号32位整数", "Two's complement", 32, "-2^31", "2^31-1"),
        ("INT64", "有符号64位整数", "Two's complement", 64, "-2^63", "2^63-1"),
        ("INT8U", "无符号8位整数", "Unsigned", 8, "0", "255"),
        ("INT16U", "无符号16位整数", "Unsigned", 16, "0", "65535"),
        ("INT32U", "无符号32位整数", "Unsigned", 32, "0", "2^32-1"),
        ("FLOAT32", "IEEE 754单精度浮点数", "IEEE 754 single", 32, "±1.18e-38", "±3.4e+38"),
        ("FLOAT64", "IEEE 754双精度浮点数", "IEEE 754 double", 64, "±2.23e-308", "±1.80e+308"),
        ("VisString255", "可见字符串（最长255字节）", "ASCII/UTF-8", None, None, None),
        ("CODED_ENUM", "编码枚举", "Enumeration", 32, None, None),
        ("OCTET_STRING", "八位组字符串", "Binary", None, None, None),
        ("TIMESTAMP", "时间戳", "IEC 61850 EntryTime", 64, None, None),
    ]
    result: dict[str, ScadaDataType] = {}
    for name, desc, enc, size, rmin, rmax in types:
        dt = ScadaDataType(
            type_name=name, description=desc, encoding=enc,
            size_bits=size, range_min=rmin, range_max=rmax,
        )
        session.add(dt); result[name] = dt
    return result


# ══════════════════════════════════════════════════════════════════════
# 3. 类型
# ══════════════════════════════════════════════════════════════════════

def _create_asset_types(session: Session) -> dict[str, AssetType]:
    types = {
        AT_WIND_TURBINE: ("电气设备", "并网型风力发电机组，含塔筒/机舱/叶轮/控制系统"),
        AT_INVERTER: ("电气设备", "光伏并网逆变器，直流转交流，含MPPT/孤岛保护"),
        AT_PV_PANEL: ("电气设备", "光伏组件，单晶/多晶硅电池板"),
        AT_PCS: ("电气设备", "储能变流器，交直流双向变换"),
        AT_BATTERY: ("电气设备", "锂电池储能系统，含电芯/模组/电池簇"),
        AT_TRANSFORMER: ("电气设备", "升压/降压变压器，油浸或干式"),
        AT_SVG: ("电气设备", "静止无功发生器，动态无功补偿与电压支撑"),
        AT_SUBSTATION: ("电气设备", "升压站/开关站，汇集集电线路并升压送出"),
        AT_SWITCHGEAR: ("电气设备", "高压/低压开关柜，含断路器/隔离开关/互感器"),
        AT_MET_STATION: ("监控设备", "风电场气象监测站，含风速/风向/温度/湿度/气压/辐照传感器"),
        AT_CABLE: ("电气设备", "电力电缆与通信光纤"),
    }
    result = {}
    for name, (cat, desc) in types.items():
        at = AssetType(asset_type_name=name, category=cat, description=desc)
        session.add(at); result[name] = at
    return result


def _create_component_types(session: Session) -> dict[str, ComponentType]:
    types = [
        (CT_BLADE, "风机叶片，捕获风能转换为旋转动能"),
        (CT_TOWER, "风机塔筒，支撑机舱至轮毂设计高度"),
        (CT_GEARBOX, "齿轮增速箱，将风轮低速大扭矩转换为发电机所需高速"),
        (CT_GENERATOR, "发电机，将机械能转换为电能，双馈异步或永磁直驱"),
        (CT_PITCH, "变桨系统，调节叶片桨距角以控制转速和功率输出"),
        (CT_CONVERTER, "变流器，AC-DC-AC 电力电子变换，实现变速恒频"),
        (CT_YAW, "偏航系统，根据风向信号驱动机舱转动使叶轮对风"),
        (CT_CONTROL, "主控系统，风机运行逻辑控制/状态监测/故障保护/通信管理"),
        (CT_ROTOR, "叶轮总成，含轮毂/导流罩/叶片连接法兰"),
        (CT_NACELLE, "机舱，容纳齿轮箱/发电机/变流器/偏航驱动等核心部件"),
        (CT_MAIN_SHAFT, "主轴，传递叶轮扭矩至齿轮箱输入轴"),
        (CT_BRAKE, "制动系统，含高速轴制动盘/偏航制动器/液压站"),
        (CT_POWER_MODULE, "IGBT 功率模块，变流器核心电力电子开关单元"),
        (CT_COOLING, "散热系统，液冷/风冷方式为变流器和发电机散热"),
        (CT_CONTROL_BOARD, "控制板，DSP/ARM 主控电路板"),
        (CT_TRACKER, "光伏跟踪支架，单轴或双轴跟踪太阳方位"),
        (CT_COMBINER, "光伏汇流箱，将多路光伏组串直流汇入逆变器"),
        (CT_BATTERY_CELL, "锂电池单体，磷酸铁锂/三元/钠离子等化学体系"),
        (CT_BMS, "电池管理系统，采集电芯电压/温度/SOC/SOH"),
        (CT_THERMAL, "储能热管理系统，液冷/风冷方式控制电池簇工作温度"),
        (CT_TRANSFORMER_COMP, "变压器铁芯与绕组组件"),
        (CT_CIRCUIT_BREAKER, "高压断路器，SF6/真空灭弧"),
    ]
    result = {}
    for name, desc in types:
        ct = ComponentType(component_type_name=name, description=desc)
        session.add(ct); result[name] = ct
    return result


# ══════════════════════════════════════════════════════════════════════
# 4. 资产型号属性定义
# ══════════════════════════════════════════════════════════════════════

def _create_asset_attributes(session: Session, at: dict, dt: dict) -> None:
    f64, i32 = dt["FLOAT64"].data_type_id, dt["INT32"].data_type_id
    s255 = dt["VisString255"].data_type_id

    for type_key, attrs in [
        (AT_WIND_TURBINE, [
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("cut_in_wind_speed_m_s", "切入风速（m/s）", f64, "m/s", "BETWEEN 0 75"),
            ("cut_out_wind_speed_m_s", "切出风速（m/s）", f64, "m/s", "BETWEEN 0 75"),
            ("rated_wind_speed_m_s", "额定风速（m/s）", f64, "m/s", "BETWEEN 0 75"),
            ("survival_wind_speed_m_s", "极限生存风速（m/s）", f64, "m/s", "BETWEEN 0 75"),
            ("rotor_diameter_m", "风轮直径（m）", f64, "m", ">= 0"),
            ("hub_height_m", "轮毂高度（m）", f64, "m", ">= 0"),
            ("rated_voltage_v", "额定电压（V）", i32, "V", ">= 0"),
            ("frequency_hz", "额定频率（Hz）", f64, "Hz", "BETWEEN 45 55"),
            ("min_operating_temp_c", "最低运行温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("max_operating_temp_c", "最高运行温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("survival_min_temp_c", "最低生存温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("survival_max_temp_c", "最高生存温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("design_life_year", "设计寿命（年）", i32, "year", ">= 0"),
            ("wind_class", "风区等级", s255, None, None),
        ]),
        (AT_INVERTER, [
            ("rated_power_kw", "额定输出功率（kW）", f64, "kW", ">= 0"),
            ("max_input_voltage_v", "最大直流输入电压（V）", i32, "V", ">= 0"),
            ("mppt_voltage_min_v", "MPPT电压下限（V）", i32, "V", ">= 0"),
            ("mppt_voltage_max_v", "MPPT电压上限（V）", i32, "V", ">= 0"),
            ("rated_output_voltage_v", "额定交流输出电压（V）", i32, "V", ">= 0"),
            ("rated_output_frequency_hz", "额定输出频率（Hz）", f64, "Hz", "BETWEEN 45 55"),
            ("max_efficiency", "最大转换效率", f64, "", "BETWEEN 0 1"),
            ("mppt_count", "MPPT路数", i32, None, ">= 0"),
            ("protection_rating", "防护等级", s255, None, None),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
        ]),
        (AT_PV_PANEL, [
            ("peak_power_wp", "峰值功率（Wp）", f64, "Wp", ">= 0"),
            ("open_circuit_voltage_v", "开路电压（V）", f64, "V", ">= 0"),
            ("short_circuit_current_a", "短路电流（A）", f64, "A", ">= 0"),
            ("voltage_at_pmax_v", "最大功率点电压（V）", f64, "V", ">= 0"),
            ("current_at_pmax_a", "最大功率点电流（A）", f64, "A", ">= 0"),
            ("module_efficiency", "组件转换效率", f64, "", "BETWEEN 0 1"),
            ("temperature_coefficient_pmax", "功率温度系数（%/℃）", f64, "%/℃", None),
            ("cell_type", "电池类型", s255, None, None),
            ("cell_count", "电池片数量", i32, None, ">= 0"),
            ("dimensions_mm", "外形尺寸（mm）", s255, None, None),
            ("weight_kg", "重量（kg）", f64, "kg", ">= 0"),
        ]),
        (AT_PCS, [
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("rated_apparent_power_kva", "额定视在功率（kVA）", f64, "kVA", ">= 0"),
            ("dc_voltage_min_v", "直流电压下限（V）", i32, "V", ">= 0"),
            ("dc_voltage_max_v", "直流电压上限（V）", i32, "V", ">= 0"),
            ("ac_rated_voltage_v", "交流额定电压（V）", i32, "V", ">= 0"),
            ("ac_rated_frequency_hz", "交流额定频率（Hz）", f64, "Hz", "BETWEEN 45 55"),
            ("max_efficiency", "最大转换效率", f64, "", "BETWEEN 0 1"),
            ("response_time_ms", "响应时间（ms）", i32, "ms", ">= 0"),
            ("cooling_method", "冷却方式", s255, None, None),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("protection_rating", "防护等级", s255, None, None),
        ]),
        (AT_BATTERY, [
            ("rated_energy_kwh", "额定能量（kWh）", f64, "kWh", ">= 0"),
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("nominal_voltage_v", "标称电压（V）", f64, "V", ">= 0"),
            ("operating_voltage_min_v", "工作电压下限（V）", f64, "V", ">= 0"),
            ("operating_voltage_max_v", "工作电压上限（V）", f64, "V", ">= 0"),
            ("chemistry_type", "电芯化学体系", s255, None, None),
            ("max_charge_c_rate", "最大充电倍率（C）", f64, "C", ">= 0"),
            ("max_discharge_c_rate", "最大放电倍率（C）", f64, "C", ">= 0"),
            ("round_trip_efficiency", "充放电往返效率", f64, "", "BETWEEN 0 1"),
            ("cycle_life", "循环寿命（次）", i32, "次", ">= 0"),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
        ]),
        (AT_TRANSFORMER, [
            ("rated_capacity_kva", "额定容量（kVA）", f64, "kVA", ">= 0"),
            ("primary_voltage_kv", "一次侧额定电压（kV）", f64, "kV", ">= 0"),
            ("secondary_voltage_kv", "二次侧额定电压（kV）", f64, "kV", ">= 0"),
            ("vector_group", "联结组别", s255, None, None),
            ("impedance_percent", "阻抗电压百分比", f64, "%", "BETWEEN 0 100"),
            ("cooling_method", "冷却方式", s255, None, None),
            ("tap_changer_type", "调压方式", s255, None, None),
        ]),
        (AT_SVG, [
            ("rated_capacity_kvar", "额定容量（kvar）", f64, "kvar", ">= 0"),
            ("rated_voltage_kv", "额定电压（kV）", f64, "kV", ">= 0"),
            ("rated_frequency_hz", "额定频率（Hz）", f64, "Hz", "BETWEEN 45 55"),
            ("response_time_ms", "响应时间（ms）", i32, "ms", ">= 0"),
            ("cooling_method", "冷却方式", s255, None, None),
            ("harmonic_compensation", "谐波补偿能力", s255, None, None),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
        ]),
    ]:
        for attr_name, desc, dt_id, unit, constraint in attrs:
            session.add(AssetAttribute(
                asset_type_id=at[type_key].asset_type_id,
                attribute_name=attr_name, description=desc, data_type_id=dt_id,
                unit=unit, constraint_expr=constraint,
            ))


# ══════════════════════════════════════════════════════════════════════
# 5. 部件型号属性定义
# ══════════════════════════════════════════════════════════════════════

def _create_component_attributes(session: Session, ct: dict, dt: dict) -> None:
    f64, i32 = dt["FLOAT64"].data_type_id, dt["INT32"].data_type_id
    s255 = dt["VisString255"].data_type_id

    for type_key, attrs in [
        (CT_BLADE, [
            ("length_m", "叶片长度（m）", f64, "m", ">= 0"),
            ("weight_kg", "重量（kg）", f64, "kg", ">= 0"),
            ("material", "材料", s255, None, None),
            ("aerodynamic_profile", "气动翼型系列", s255, None, None),
            ("suitable_rotor_diameter_m", "适配风轮直径（m）", f64, "m", ">= 0"),
            ("design_life_year", "设计寿命（年）", i32, "year", ">= 0"),
        ]),
        (CT_TOWER, [
            ("hub_height_m", "轮毂高度（m）", f64, "m", ">= 0"),
            ("top_diameter_m", "顶部直径（m）", f64, "m", ">= 0"),
            ("bottom_diameter_m", "底部直径（m）", f64, "m", ">= 0"),
            ("sections_count", "分段数量", i32, None, ">= 0"),
            ("material", "材料", s255, None, None),
            ("suitable_power_kw", "适配功率范围（kW）", f64, "kW", ">= 0"),
        ]),
        (CT_GEARBOX, [
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("ratio", "传动比", f64, None, ">= 0"),
            ("input_rpm", "额定输入转速（rpm）", f64, "rpm", ">= 0"),
            ("output_rpm", "额定输出转速（rpm）", f64, "rpm", ">= 0"),
            ("stages_count", "级数", i32, None, ">= 0"),
            ("weight_kg", "重量（kg）", f64, "kg", ">= 0"),
            ("design_life_year", "设计寿命（年）", i32, "year", ">= 0"),
        ]),
        (CT_GENERATOR, [
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("rated_voltage_v", "额定电压（V）", i32, "V", ">= 0"),
            ("rated_rpm", "额定转速（rpm）", i32, "rpm", ">= 0"),
            ("rated_frequency_hz", "额定频率（Hz）", f64, "Hz", "BETWEEN 45 55"),
            ("efficiency", "额定效率", f64, "", "BETWEEN 0 1"),
            ("cooling_type", "冷却方式", s255, None, None),
            ("insulation_class", "绝缘等级", s255, None, None),
            ("protection_rating", "防护等级", s255, None, None),
            ("generator_type", "发电机类型", s255, None, None),
        ]),
        (CT_PITCH, [
            ("actuation_type", "驱动方式", s255, None, None),
            ("response_time_ms", "响应时间（ms）", i32, "ms", ">= 0"),
            ("max_pitch_rate_deg_s", "最大变桨速率（°/s）", f64, "°/s", ">= 0"),
            ("redundancy", "冗余配置", s255, None, None),
            ("emergency_stop_time_ms", "紧急顺桨时间（ms）", i32, "ms", ">= 0"),
        ]),
        (CT_CONVERTER, [
            ("rated_power_kw", "额定功率（kW）", f64, "kW", ">= 0"),
            ("grid_side_voltage_v", "网侧额定电压（V）", i32, "V", ">= 0"),
            ("generator_side_voltage_v", "机侧额定电压（V）", i32, "V", ">= 0"),
            ("dc_link_voltage_v", "直流母线电压（V）", i32, "V", ">= 0"),
            ("switching_frequency_hz", "开关频率（Hz）", i32, "Hz", ">= 0"),
            ("cooling_method", "冷却方式", s255, None, None),
            ("protection_rating", "防护等级", s255, None, None),
        ]),
        (CT_YAW, [
            ("motor_count", "偏航电机数量", i32, None, ">= 0"),
            ("max_yaw_rate_deg_s", "最大偏航速率（°/s）", f64, "°/s", ">= 0"),
            ("brake_type", "制动方式", s255, None, None),
            ("bearing_type", "轴承类型", s255, None, None),
            ("lubrication_type", "润滑方式", s255, None, None),
        ]),
        (CT_CONTROL, [
            ("controller_platform", "控制器平台", s255, None, None),
            ("communication_protocol", "通信协议", s255, None, None),
            ("safety_integrity_level", "安全完整性等级", s255, None, None),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
        ]),
        (CT_TRACKER, [
            ("tracking_type", "跟踪方式", s255, None, None),
            ("tracking_range_deg", "跟踪角度范围", s255, None, None),
            ("suitable_module_count", "适配组件数量", i32, None, ">= 0"),
            ("drive_type", "驱动方式", s255, None, None),
            ("wind_resistance_m_s", "设计抗风能力（m/s）", f64, "m/s", ">= 0"),
        ]),
        (CT_COMBINER, [
            ("input_string_count", "输入组串数", i32, None, ">= 0"),
            ("max_input_voltage_v", "最大输入电压（V）", i32, "V", ">= 0"),
            ("max_output_current_a", "最大输出电流（A）", f64, "A", ">= 0"),
            ("protection_rating", "防护等级", s255, None, None),
            ("has_monitoring", "是否带监控功能", i32, None, None),
        ]),
        (CT_BATTERY_CELL, [
            ("chemistry", "化学体系", s255, None, None),
            ("nominal_voltage_v", "标称电压（V）", f64, "V", ">= 0"),
            ("capacity_ah", "额定容量（Ah）", f64, "Ah", ">= 0"),
            ("energy_density_wh_kg", "质量能量密度（Wh/kg）", f64, "Wh/kg", ">= 0"),
            ("max_charge_c_rate", "最大充电倍率（C）", f64, "C", ">= 0"),
            ("max_discharge_c_rate", "最大放电倍率（C）", f64, "C", ">= 0"),
            ("cycle_life", "循环寿命（次）", i32, "次", ">= 0"),
            ("operating_temp_min_c", "最低工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("form_factor", "封装形式", s255, None, None),
        ]),
        (CT_BMS, [
            ("topology", "拓扑架构", s255, None, None),
            ("max_cell_series_count", "最大串联电芯数", i32, None, ">= 0"),
            ("balancing_method", "均衡方式", s255, None, None),
            ("balancing_current_a", "均衡电流（A）", f64, "A", ">= 0"),
            ("communication_protocol", "通信协议", s255, None, None),
            ("voltage_accuracy_mv", "电压采集精度（mV）", f64, "mV", ">= 0"),
            ("temperature_accuracy_c", "温度采集精度（℃）", f64, "deg C", ">= 0"),
        ]),
        (CT_THERMAL, [
            ("cooling_type", "冷却方式", s255, None, None),
            ("cooling_capacity_kw", "制冷量（kW）", f64, "kW", ">= 0"),
            ("heating_capacity_kw", "制热量（kW）", f64, "kW", ">= 0"),
            ("operating_temp_min_c", "最低工作环境温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("operating_temp_max_c", "最高工作环境温度（℃）", f64, "deg C", "BETWEEN -40 80"),
            ("coolant_type", "冷却介质", s255, None, None),
            ("noise_level_db", "噪声等级（dB）", f64, "dB", ">= 0"),
        ]),
    ]:
        for attr_name, desc, dt_id, unit, constraint in attrs:
            session.add(ComponentAttribute(
                component_type_id=ct[type_key].component_type_id,
                attribute_name=attr_name, description=desc, data_type_id=dt_id,
                unit=unit, constraint_expr=constraint,
            ))


# ══════════════════════════════════════════════════════════════════════
# 6. 型号
# ══════════════════════════════════════════════════════════════════════

def _create_asset_models(session: Session, at: dict) -> dict:
    def _add(asset_type_name, model_name, manufacturer, **specs):
        m = AssetModel(
            asset_type_id=at[asset_type_name].asset_type_id,
            model_name=model_name, manufacturer=manufacturer,
            specifications=specs,
        )
        session.add(m); return m

    wt = _add(AT_WIND_TURBINE, "金风GW121/2500", "金风科技",
              rated_power_kw=2500.0, cut_in_wind_speed_m_s=3.0,
              cut_out_wind_speed_m_s=25.0, rated_wind_speed_m_s=12.0,
              survival_wind_speed_m_s=59.5, rotor_diameter_m=121.0,
              hub_height_m=90.0, rated_voltage_v=690, frequency_hz=50.0,
              min_operating_temp_c=-30.0, max_operating_temp_c=40.0,
              survival_min_temp_c=-40.0, survival_max_temp_c=50.0,
              design_life_year=20, wind_class="IEC IIA")

    pv_inv = _add(AT_INVERTER, "华为SUN2000-300KTL-H0", "华为",
                  rated_power_kw=300.0, max_input_voltage_v=1500,
                  mppt_voltage_min_v=500, mppt_voltage_max_v=1500,
                  rated_output_voltage_v=800, rated_output_frequency_hz=50.0,
                  max_efficiency=0.99, mppt_count=8, protection_rating="IP66",
                  operating_temp_min_c=-25.0, operating_temp_max_c=60.0)

    pv_panel = _add(AT_PV_PANEL, "隆基LR5-72HBD-540M", "隆基绿能",
                    peak_power_wp=540.0, open_circuit_voltage_v=49.6,
                    short_circuit_current_a=13.86, voltage_at_pmax_v=41.7,
                    current_at_pmax_a=12.95, module_efficiency=0.212,
                    temperature_coefficient_pmax=-0.34,
                    cell_type="单晶P型PERC", cell_count=144,
                    dimensions_mm="2256×1133×35", weight_kg=28.5)

    pcs = _add(AT_PCS, "阳光电源SC2000UD-MV", "阳光电源",
               rated_power_kw=2000.0, rated_apparent_power_kva=2200.0,
               dc_voltage_min_v=600, dc_voltage_max_v=1500,
               ac_rated_voltage_v=690, ac_rated_frequency_hz=50.0,
               max_efficiency=0.987, response_time_ms=50,
               cooling_method="液冷", operating_temp_min_c=-30.0,
               operating_temp_max_c=55.0, protection_rating="IP54")

    battery = _add(AT_BATTERY, "宁德时代EnerOne-3727", "宁德时代",
                   rated_energy_kwh=3727.0, rated_power_kw=1864.0,
                   nominal_voltage_v=1331.0, operating_voltage_min_v=1165.0,
                   operating_voltage_max_v=1498.0, chemistry_type="LFP",
                   max_charge_c_rate=1.0, max_discharge_c_rate=1.0,
                   round_trip_efficiency=0.89, cycle_life=12000,
                   operating_temp_min_c=-20.0, operating_temp_max_c=45.0)

    transformer = _add(AT_TRANSFORMER, "特变电工SZ11-50000/110", "特变电工",
                       rated_capacity_kva=50000.0, primary_voltage_kv=110.0,
                       secondary_voltage_kv=35.0, vector_group="YNd11",
                       impedance_percent=10.5, cooling_method="ONAN",
                       tap_changer_type="有载调压")

    svg = _add(AT_SVG, "思源电气QNSVG-20/35", "思源电气",
               rated_capacity_kvar=20000.0, rated_voltage_kv=35.0,
               rated_frequency_hz=50.0, response_time_ms=5,
               cooling_method="风冷", harmonic_compensation="2~25次",
               operating_temp_min_c=-25.0, operating_temp_max_c=45.0)

    return {"wt": wt, "pv_inv": pv_inv, "pv_panel": pv_panel, "pcs": pcs,
            "battery": battery, "transformer": transformer, "svg": svg}


def _create_component_models(session: Session, ct: dict) -> dict:
    def _add(component_type_name, model_name, manufacturer, **specs):
        m = ComponentModel(
            component_type_id=ct[component_type_name].component_type_id,
            model_name=model_name, manufacturer=manufacturer,
            specifications=specs,
        )
        session.add(m); return m

    blade = _add(CT_BLADE, "LM 61.5 P2", "LM Wind Power",
                 length_m=61.5, weight_kg=18500.0, material="玻璃纤维增强环氧树脂",
                 aerodynamic_profile="NACA63-4xx系列", suitable_rotor_diameter_m=121.0,
                 design_life_year=20)

    tower = _add(CT_TOWER, "ST-90/2500", "天顺风能",
                 hub_height_m=90.0, top_diameter_m=3.2, bottom_diameter_m=4.3,
                 sections_count=4, material="Q420ME钢材", suitable_power_kw=2500.0)

    gearbox = _add(CT_GEARBOX, "Winergy PEAB 4440", "Winergy",
                   rated_power_kw=2800.0, ratio=118.0, input_rpm=15.0,
                   output_rpm=1770.0, stages_count=3, weight_kg=32000.0,
                   design_life_year=20)

    generator = _add(CT_GENERATOR, "ABB AMK 500L6L", "ABB",
                     rated_power_kw=2600.0, rated_voltage_v=690, rated_rpm=1800,
                     rated_frequency_hz=50.0, efficiency=0.971, cooling_type="IC616",
                     insulation_class="H", protection_rating="IP54", generator_type="双馈异步")

    pitch = _add(CT_PITCH, "SSB PE3-290", "SSB Wind",
                 actuation_type="电动", response_time_ms=100, max_pitch_rate_deg_s=8.0,
                 redundancy="3轴独立+超级电容后备", emergency_stop_time_ms=3000)

    converter = _add(CT_CONVERTER, "ABB ACS880-87C", "ABB",
                     rated_power_kw=2800.0, grid_side_voltage_v=690,
                     generator_side_voltage_v=690, dc_link_voltage_v=1100,
                     switching_frequency_hz=2500, cooling_method="液冷", protection_rating="IP54")

    yaw_system = _add(CT_YAW, "Zollern ZYAW-2500", "Zollern",
                      motor_count=4, max_yaw_rate_deg_s=0.5, brake_type="液压",
                      bearing_type="滑动轴承", lubrication_type="自动集中润滑")

    control_system = _add(CT_CONTROL, "Bachmann M1", "Bachmann",
                          controller_platform="ARM Cortex-A9 + FPGA",
                          communication_protocol="IEC 61850 / Modbus TCP / CANopen",
                          safety_integrity_level="SIL2",
                          operating_temp_min_c=-30.0, operating_temp_max_c=60.0)

    tracker = _add(CT_TRACKER, "中信博天际单轴", "中信博",
                   tracking_type="单轴平单轴", tracking_range_deg="-55°~+55°",
                   suitable_module_count=90, drive_type="电动推杆", wind_resistance_m_s=45.0)

    combiner = _add(CT_COMBINER, "许继PVA-16H", "许继电气",
                    input_string_count=16, max_input_voltage_v=1500,
                    max_output_current_a=250.0, protection_rating="IP65", has_monitoring=1)

    cell = _add(CT_BATTERY_CELL, "CATL-LFP-280Ah", "宁德时代",
                chemistry="LFP", nominal_voltage_v=3.2, capacity_ah=280.0,
                energy_density_wh_kg=165.0, max_charge_c_rate=1.0,
                max_discharge_c_rate=1.0, cycle_life=12000,
                operating_temp_min_c=-20.0, operating_temp_max_c=55.0,
                form_factor="方形铝壳")

    bms = _add(CT_BMS, "科工BMS-LFP-3S", "科工电子",
               topology="三级架构（BMU/BCMU/BAMS）", max_cell_series_count=320,
               balancing_method="主动均衡", balancing_current_a=2.0,
               communication_protocol="CAN 2.0B + Modbus RTU",
               voltage_accuracy_mv=5.0, temperature_accuracy_c=1.0)

    thermal = _add(CT_THERMAL, "英维克EC-X20", "英维克",
                   cooling_type="液冷", cooling_capacity_kw=20.0,
                   heating_capacity_kw=10.0, operating_temp_min_c=-30.0,
                   operating_temp_max_c=55.0, coolant_type="50%乙二醇溶液",
                   noise_level_db=65.0)

    return {"blade": blade, "tower": tower, "gearbox": gearbox, "generator": generator,
            "pitch": pitch, "converter": converter, "yaw_system": yaw_system,
            "control_system": control_system,
            "tracker": tracker, "combiner": combiner,
            "cell": cell, "bms": bms, "thermal": thermal}


# ══════════════════════════════════════════════════════════════════════
# 7. BOM + CDC/FC
# ══════════════════════════════════════════════════════════════════════

def _create_bom(session: Session, at: dict, am: dict, ct: dict, cm: dict) -> None:
    for comp_type_key, comp_model_key, qty in [
        (CT_BLADE, "blade", 3), (CT_TOWER, "tower", 1),
        (CT_GEARBOX, "gearbox", 1), (CT_GENERATOR, "generator", 1),
        (CT_PITCH, "pitch", 1), (CT_CONVERTER, "converter", 1),
        (CT_YAW, "yaw_system", 1), (CT_CONTROL, "control_system", 1),
    ]:
        session.add(AssetBOM(
            asset_type_id=at[AT_WIND_TURBINE].asset_type_id,
            asset_model_id=am["wt"].model_id,
            component_type_id=ct[comp_type_key].component_type_id,
            component_model_id=cm[comp_model_key].model_id,
            quantity=qty,
        ))


def _create_cdc_fc_dicts(session: Session) -> None:
    for code, name, desc in [
        ("MV", "Measured Value", "测量值（模拟量）"),
        ("STV", "Status Value", "状态值"),
        ("SPS", "Single Point Status", "单点状态"),
        ("SPC", "Single Point Controllable", "单点可控"),
        ("ACT", "Analogue Set Point", "模拟设点"),
        ("ACD", "Analogue Control", "模拟控制"),
        ("INC", "Integer Controllable", "整数可控"),
        ("INS", "Integer Status", "整数状态"),
        ("BCR", "Binary Counter", "二进制计数器"),
        ("WYE", "Wye (Phase-to-Neutral)", "星形三相复数"),
        ("DEL", "Delta (Phase-to-Phase)", "三角形三相复数"),
        ("CMD", "Command", "命令"),
        ("DPC", "Double Point Controllable", "双点可控"),
        ("DPL", "Double Point Status", "双点状态"),
        ("ENC", "Enumerated Controllable", "枚举可控"),
        ("ENG", "Enumerated Status", "枚举状态"),
        ("HMV", "Harmonic Measured Value", "谐波测量值"),
        ("HST", "Harmonic Status", "谐波状态"),
        ("LPL", "Logical Node Name Plate", "逻辑节点铭牌"),
        ("LPC", "Logical Node Control", "逻辑节点控制"),
        ("CSD", "Curve Shape Description", "曲线形状描述"),
        ("CST", "Curve Status", "曲线状态"),
        ("ISC", "Integer Status Controllable", "整数状态可控"),
    ]:
        session.add(CDCDict(cdc_code=code, cdc_name=name, description=desc))
    for code, name, desc in [
        ("ST", "Status", "状态信息"),
        ("MX", "Measurands", "测量量（模拟值）"),
        ("CF", "Configuration", "配置"),
        ("DC", "Description", "描述"),
        ("SG", "Setting Group", "定值组"),
        ("SE", "Setting Group Editing", "定值组编辑"),
        ("SP", "Set Point", "设点"),
        ("SV", "Substitution Values", "替代值"),
        ("CO", "Control", "控制"),
        ("EX", "Extended Definition", "扩展定义"),
        ("BR", "Buffered Report", "缓冲报告"),
        ("RP", "Unbuffered Report", "非缓冲报告"),
        ("LG", "Logging", "日志"),
        ("GO", "GOOSE Control", "GOOSE 控制"),
        ("GS", "GSSE Control", "GSSE 控制"),
        ("MS", "Multicast Sampled Values", "多播采样值"),
        ("US", "Unicast Sampled Values", "单播采样值"),
    ]:
        session.add(FCDict(fc_code=code, fc_name=name, description=desc))


# ══════════════════════════════════════════════════════════════════════
# 8. 资产实例
# ══════════════════════════════════════════════════════════════════════

def _create_asset_instances(session: Session, at: dict, am: dict, plant: Organization) -> dict:
    wt_type, wt_model = at[AT_WIND_TURBINE], am["wt"]
    install_base = date(2024, 6, 1)
    turbines = []
    for i in range(1, TURBINE_COUNT + 1):
        a = AssetInstance(
            asset_code=f"ZB-WTG-{i:03d}", asset_type_id=wt_type.asset_type_id,
            model_id=wt_model.model_id, org_id=plant.org_id,
            installation_date=install_base + timedelta(days=i * 7),
            location=f"机位#{i}",
        )
        session.add(a); turbines.append(a)
    for i in range(1, 4):
        session.add(AssetInstance(
            asset_code=f"ZB-XF-{i:03d}", asset_type_id=at[AT_TRANSFORMER].asset_type_id,
            model_id=am["transformer"].model_id, org_id=plant.org_id,
            installation_date=install_base, location=f"箱变#{i}"))
    session.add(AssetInstance(asset_code="ZB-INV-001", asset_type_id=at[AT_INVERTER].asset_type_id,
                              model_id=am["pv_inv"].model_id, org_id=plant.org_id,
                              installation_date=install_base, location="光伏区-A"))
    session.add(AssetInstance(asset_code="ZB-BAT-001", asset_type_id=at[AT_BATTERY].asset_type_id,
                              model_id=am["battery"].model_id, org_id=plant.org_id,
                              installation_date=install_base + timedelta(days=30), location="储能区-1号舱"))
    session.add(AssetInstance(asset_code="ZB-SVG-001", asset_type_id=at[AT_SVG].asset_type_id,
                              model_id=am["svg"].model_id, org_id=plant.org_id,
                              installation_date=install_base, location="升压站35kV侧"))
    session.add(AssetInstance(asset_code="ZB-PCS-001", asset_type_id=at[AT_PCS].asset_type_id,
                              model_id=am["pcs"].model_id, org_id=plant.org_id,
                              installation_date=install_base + timedelta(days=30), location="储能区-PCS舱"))
    session.add(AssetInstance(asset_code="ZB-MET-001", asset_type_id=at[AT_MET_STATION].asset_type_id,
                              org_id=plant.org_id, installation_date=install_base, location="升压站气象塔(100m)"))
    session.add(AssetInstance(asset_code="ZB-SUB-001", asset_type_id=at[AT_SUBSTATION].asset_type_id,
                              org_id=plant.org_id, installation_date=install_base, location="升压站110kV"))
    panels = []
    for i in range(1, 6):
        p = AssetInstance(asset_code=f"ZB-PV-{i:03d}", asset_type_id=at[AT_PV_PANEL].asset_type_id,
                          model_id=am["pv_panel"].model_id, org_id=plant.org_id,
                          installation_date=install_base + timedelta(days=60), location=f"光伏区-阵列{i}")
        session.add(p); panels.append(p)
    return {"turbines": turbines, "panels": panels}


# ══════════════════════════════════════════════════════════════════════
# 9. 部件实例
# ══════════════════════════════════════════════════════════════════════

def _create_component_instances(session: Session, ct: dict, cm: dict,
                                 turbines: list[AssetInstance]) -> None:
    install_base = date(2024, 6, 1)
    for i, turbine in enumerate(turbines):
        for b in range(1, 4):
            session.add(ComponentInstance(
                component_type_id=ct[CT_BLADE].component_type_id,
                component_model_id=cm["blade"].model_id,
                asset_instance_id=turbine.asset_instance_id,
                installation_date=install_base + timedelta(days=i * 7)))
        for comp_type_key, comp_model_key in [
            (CT_TOWER, "tower"), (CT_GEARBOX, "gearbox"),
            (CT_GENERATOR, "generator"), (CT_PITCH, "pitch"),
            (CT_CONVERTER, "converter"), (CT_YAW, "yaw_system"),
            (CT_CONTROL, "control_system"),
        ]:
            session.add(ComponentInstance(
                component_type_id=ct[comp_type_key].component_type_id,
                component_model_id=cm[comp_model_key].model_id,
                asset_instance_id=turbine.asset_instance_id,
                installation_date=install_base + timedelta(days=i * 7)))


# ══════════════════════════════════════════════════════════════════════
# 10. IED 模板
# ══════════════════════════════════════════════════════════════════════

def _create_ied_template(session: Session, all_logical_nodes: list, ld_name: str,
                         data_types: dict[str, ScadaDataType]) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    do_count = 0
    for node_def in all_logical_nodes:
        ln = LN(ln_name=node_def.name, ld_id=ld.ld_id, description=node_def.desc)
        session.add(ln); session.flush()
        for field in node_def.fields:
            type_name = field.data_type
            dt_id = data_types[type_name].data_type_id
            session.add(DO(
                ln_id=ln.ln_id, do_name=field.key,
                cdc=field.cdc, fc="MX" if field.cdc == "MV" else "ST",
                data_type_id=dt_id,
                unit=field.unit if field.unit else None,
                constraint_expr=_constraint_for(field),
                display_name=field.desc,
            ))
            do_count += 1
    return ied, do_count


def _create_met_ied_template(session: Session, ld_name: str,
                              data_types: dict[str, ScadaDataType]) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    ln = LN(ln_name="WMET", ld_id=ld.ld_id, description="气象信息")
    session.add(ln); session.flush()
    do_count = 0
    f64_id = data_types["FLOAT64"].data_type_id
    for key, unit, desc, constraint in [
        ("WSpd", "m/s", "风速", "BETWEEN 0 75"), ("WSpdMax", "m/s", "最大风速", "BETWEEN 0 75"),
        ("WSpdMin", "m/s", "最小风速", "BETWEEN 0 75"), ("Wdir", "deg", "风向", "BETWEEN 0 360"),
        ("Tmp", "deg C", "环境温度", "BETWEEN -40 60"), ("Hum", "%", "相对湿度", "BETWEEN 0 100"),
        ("Press", "hPa", "大气压力", "BETWEEN 500 1100"), ("Rain", "mm", "降水量", ">= 0"),
        ("Rad", "W/m²", "太阳辐照度", "BETWEEN 0 1500"),
    ]:
        session.add(DO(ln_id=ln.ln_id, do_name=key, cdc="MV", fc="MX",
                       data_type_id=f64_id, unit=unit, constraint_expr=constraint, display_name=desc))
        do_count += 1
    return ied, do_count


def _create_substation_ied_template(session: Session, ld_name: str,
                                     data_types: dict[str, ScadaDataType]) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    ln = LN(ln_name="MMXU", ld_id=ld.ld_id, description="测量单元")
    session.add(ln); session.flush()
    do_count = 0
    f64_id = data_types["FLOAT64"].data_type_id
    for key, unit, desc, constraint in [
        ("PhV", "V", "相电压", "BETWEEN 0 126000"), ("A", "A", "相电流", "BETWEEN 0 5000"),
        ("W", "kW", "有功功率", "BETWEEN -50000 150000"), ("VAr", "kVAr", "无功功率", "BETWEEN -20000 20000"),
        ("Hz", "Hz", "频率", "BETWEEN 49 51"), ("PF", "", "功率因数", "BETWEEN -1 1"),
    ]:
        session.add(DO(ln_id=ln.ln_id, do_name=key, cdc="MV", fc="MX",
                       data_type_id=f64_id, unit=unit, constraint_expr=constraint, display_name=desc))
        do_count += 1
    return ied, do_count


def _constraint_for(field) -> str | None:
    cdc, key, unit = field.cdc, field.key, field.unit
    if cdc in ("STV", "SPS", "SPC", "DPC", "INC", "INS", "BCR"):
        return ">= 0"
    if key in ("TurSt", "DevSt"):
        return "IN 0 1 2 3 4 5"
    if key == "Gra":
        return "BETWEEN -90 90"
    if unit in ("kW", "kWh", "kVAr", "kVArh", "A", "V"):
        return ">= 0"
    if unit in ("Hz",):
        return "BETWEEN 45 55"
    if unit in ("deg C",):
        return "BETWEEN -40 80"
    if unit in ("m/s",):
        return "BETWEEN 0 75"
    if unit in ("deg",):
        return "BETWEEN 0 360"
    if unit in ("%",):
        return "BETWEEN 0 100"
    if unit in ("h",):
        return ">= 0"
    return None


# ══════════════════════════════════════════════════════════════════════
# 11. 采集任务
# ══════════════════════════════════════════════════════════════════════

def _create_acquisition_tasks(session: Session, turbines: list, ied: IED,
                               met_ied: IED, sub_ied: IED) -> list:
    tasks = []
    for i, t in enumerate(turbines):
        task = AcquisitionTask(
            task_name=f"task_{t.asset_code}", asset_instance_id=t.asset_instance_id,
            asset_type_id=t.asset_type_id,
            ied_id=ied.ied_id, protocol_type="OPC_UA",
            endpoint=f"opc.tcp://192.168.{100 + i // 256}.{i % 256}:4840",
            namespace_uri="http://www.goldwind.com/ns", sampling_interval_ms=1000,
            acquisition_mode="SUBSCRIPTION",
            params={"security_policy": "Basic256Sha256", "security_mode": "SignAndEncrypt"},
        )
        session.add(task); tasks.append(task)
    for name, asset_code, ied_obj, endpoint, mode, interval in [
        ("task_ZB-MET-001", "ZB-MET-001", met_ied, "opc.tcp://192.168.200.1:4840", "POLLING", 5000),
        ("task_ZB-SUB-001", "ZB-SUB-001", sub_ied, "opc.tcp://192.168.200.10:4840", "SUBSCRIPTION", 500),
    ]:
        asset = session.query(AssetInstance).filter(
            AssetInstance.asset_code == asset_code).first()
        session.add(AcquisitionTask(
            task_name=name, asset_instance_id=asset.asset_instance_id,
            asset_type_id=asset.asset_type_id,
            ied_id=ied_obj.ied_id,
            protocol_type="OPC_UA", endpoint=endpoint, sampling_interval_ms=interval,
            acquisition_mode=mode, priority=1))
        tasks.append(None)
    return tasks


# ══════════════════════════════════════════════════════════════════════
# 12. DO 初始状态
# ══════════════════════════════════════════════════════════════════════

def _create_do_states(session: Session) -> int:
    from whale.shared.persistence.template.gbt_30966_fields import ALL_LOGICAL_NODES
    now = datetime.now(tz=UTC)
    count = 0
    field_means = {}
    for node in ALL_LOGICAL_NODES:
        for f in node.fields:
            field_means[f.key] = f.mean
    for code in ("ZB-WTG-001", "ZB-WTG-002", "ZB-WTG-003"):
        turbine = session.query(AssetInstance).filter(AssetInstance.asset_code == code).first()
        if not turbine: continue
        task = session.query(AcquisitionTask).filter(AcquisitionTask.task_name == f"task_{code}").first()
        if not task: continue
        dos = session.query(DO).join(DO.ln).join(LN.ld).join(LD.ied).filter(
            IED.ied_name == "IED_WTG_OPCUA").limit(50).all()
        for do in dos:
            session.add(DOState(task_id=task.task_id, asset_instance_id=turbine.asset_instance_id,
                                do_id=do.do_id,
                                value=str(field_means.get(do.do_name, 0.0)),
                                source_observed_at=now - timedelta(seconds=1)))
            count += 1
    met_task = session.query(AcquisitionTask).filter(AcquisitionTask.task_name == "task_ZB-MET-001").first()
    met_asset = session.query(AssetInstance).filter(AssetInstance.asset_code == "ZB-MET-001").first()
    if met_task and met_asset:
        met_vals = {"WSpd": "8.5", "Tmp": "22.5", "Hum": "45.0", "Press": "1013.2", "Rain": "0.0", "Rad": "850.0"}
        for do in session.query(DO).join(DO.ln).join(LN.ld).join(LD.ied).filter(IED.ied_name == "IED_MET_OPCUA").all():
            session.add(DOState(task_id=met_task.task_id, asset_instance_id=met_asset.asset_instance_id,
                                do_id=do.do_id, value=met_vals.get(do.display_name or "", "0.0"),
                                source_observed_at=now))
            count += 1
    return count


# ══════════════════════════════════════════════════════════════════════
# 13. 发件箱
# ══════════════════════════════════════════════════════════════════════

def _create_outbox_samples(session: Session) -> int:
    import json
    now = datetime.now(tz=UTC)
    count = 0
    for task in session.query(AcquisitionTask).limit(3).all():
        for j in range(2):
            sid = str(uuid.uuid4())
            session.add(StateSnapshotOutbox(
                task_id=task.task_id, asset_instance_id=task.asset_instance_id,
                message_id=str(uuid.uuid4()), snapshot_id=sid, schema_version="v1",
                message_type="state_snapshot",
                payload=json.dumps({"snapshot_id": sid, "task_name": task.task_name}),
                snapshot_at=now - timedelta(minutes=5 * j)))
            count += 1
    return count


# ══════════════════════════════════════════════════════════════════════
# 14. 拓扑
# ══════════════════════════════════════════════════════════════════════

def _create_topology(session: Session, assets: dict) -> int:
    count = 0
    turbines = assets["turbines"]

    xf1 = session.query(AssetInstance).filter(AssetInstance.asset_code == "ZB-XF-001").first()
    xf2 = session.query(AssetInstance).filter(AssetInstance.asset_code == "ZB-XF-002").first()
    xf3 = session.query(AssetInstance).filter(AssetInstance.asset_code == "ZB-XF-003").first()
    sub = session.query(AssetInstance).filter(AssetInstance.asset_code == "ZB-SUB-001").first()

    groups = [(turbines[:10], xf1), (turbines[10:20], xf2), (turbines[20:30], xf3)]
    for group_turbines, xf in groups:
        for t in group_turbines:
            if xf:
                session.add(ElectricalTopology(
                    topo_name=f"ELEC_{t.asset_code}_TO_{xf.asset_code}",
                    source_asset_instance_id=t.asset_instance_id,
                    target_asset_instance_id=xf.asset_instance_id,
                    voltage_level_kv=35.0, topology_type="radial",
                    cable_type="YJV22-26/35kV-3×95mm²", cable_length_m=500.0 + len(group_turbines) * 50,
                ))
                count += 1

    for xf in (xf1, xf2, xf3):
        if xf and sub:
            session.add(ElectricalTopology(
                topo_name=f"ELEC_{xf.asset_code}_TO_{sub.asset_code}",
                source_asset_instance_id=xf.asset_instance_id,
                target_asset_instance_id=sub.asset_instance_id,
                voltage_level_kv=110.0, topology_type="radial",
                cable_type="YJLW03-64/110kV-1×400mm²", cable_length_m=2000.0,
            ))
            count += 1

    for t in turbines[:5]:
        session.add(NetworkTopology(
            topo_name=f"NET_{t.asset_code}_TO_SW01",
            source_asset_instance_id=t.asset_instance_id,
            target_device="汇聚交换机-SW01",
            source_ip=f"192.168.{100 + (int(t.asset_code.split('-')[2]) - 1) // 256}.{int(t.asset_code.split('-')[2]) - 1}",
            target_ip="192.168.1.1", subnet_mask="255.255.255.0",
            protocol="OPC UA", port=4840, vlan_id=100,
            fiber_type="单模", redundancy_protocol="RSTP",
        ))
        count += 1

    if sub:
        session.add(NetworkTopology(
            topo_name=f"NET_{sub.asset_code}_TO_SW00",
            source_asset_instance_id=sub.asset_instance_id,
            target_device="核心交换机-SW00",
            source_ip="192.168.200.10", target_ip="192.168.1.254",
            subnet_mask="255.255.255.0",
            protocol="IEC 61850", port=102, vlan_id=200,
            fiber_type="单模", redundancy_protocol="MRP",
        ))
        count += 1

    return count


# ══════════════════════════════════════════════════════════════════════
# 15. 宽表视图（每个 model_id 一行，attribute_name 作为列）
# ══════════════════════════════════════════════════════════════════════

# Chinese type name → English view name and model table
_ASSET_WIDE_VIEWS = {
    "风力发电机": "v_asset_model_wind_turbine",
    "逆变器": "v_asset_model_pv_inverter",
    "光伏面板": "v_asset_model_pv_panel",
    "储能变流器": "v_asset_model_pcs",
    "储能系统": "v_asset_model_battery_system",
    "变压器": "v_asset_model_transformer",
    "SVG无功补偿": "v_asset_model_svg",
}

_COMPONENT_WIDE_VIEWS = {
    "叶片": "v_component_model_blade",
    "塔筒": "v_component_model_tower",
    "齿轮箱": "v_component_model_gearbox",
    "发电机": "v_component_model_generator",
    "变桨系统": "v_component_model_pitch_system",
    "变流器": "v_component_model_converter",
    "偏航系统": "v_component_model_yaw_system",
    "控制系统": "v_component_model_control_system",
    "跟踪支架": "v_component_model_tracker",
    "汇流箱": "v_component_model_combiner_box",
    "电池单体": "v_component_model_battery_cell",
    "电池管理系统": "v_component_model_bms",
    "热管理系统": "v_component_model_thermal_management",
}


def _create_wide_model_views(session: Session) -> int:
    """Create wide-format type-specific views (one row per model_id).

    Columns: model_id, model_name, manufacturer, <type_id>, <type_name>,
             plus one column per attribute (from JSON specifications).

    Replaces the tall-format wrapper views previously created by init_db.
    """
    from sqlalchemy import text

    count = 0

    for type_name, view_name in _ASSET_WIDE_VIEWS.items():
        attrs = session.query(AssetAttribute).join(AssetType).filter(
            AssetType.asset_type_name == type_name
        ).order_by(AssetAttribute.attribute_id).all()
        if not attrs:
            continue

        attr_cols = ",\n    ".join(
            f"json_extract(am.specifications, '$.{a.attribute_name}') AS {a.attribute_name}"
            for a in attrs
        )
        sql = f"""
        CREATE VIEW IF NOT EXISTS {view_name} AS
        SELECT
            am.model_id,
            am.model_name,
            am.manufacturer,
            at.asset_type_id,
            at.asset_type_name,
            {attr_cols}
        FROM asset_model am
        JOIN asset_type at ON at.asset_type_id = am.asset_type_id
        WHERE at.asset_type_name = '{type_name}'
        """
        session.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
        session.execute(text(sql))
        count += 1

    for type_name, view_name in _COMPONENT_WIDE_VIEWS.items():
        attrs = session.query(ComponentAttribute).join(ComponentType).filter(
            ComponentType.component_type_name == type_name
        ).order_by(ComponentAttribute.attribute_id).all()
        if not attrs:
            continue

        attr_cols = ",\n    ".join(
            f"json_extract(cm.specifications, '$.{a.attribute_name}') AS {a.attribute_name}"
            for a in attrs
        )
        sql = f"""
        CREATE VIEW IF NOT EXISTS {view_name} AS
        SELECT
            cm.model_id,
            cm.model_name,
            cm.manufacturer,
            ct.component_type_id,
            ct.component_type_name,
            {attr_cols}
        FROM component_model cm
        JOIN component_type ct ON ct.component_type_id = cm.component_type_id
        WHERE ct.component_type_name = '{type_name}'
        """
        session.execute(text(f"DROP VIEW IF EXISTS {view_name}"))
        session.execute(text(sql))
        count += 1

    return count


if __name__ == "__main__":
    init_db(force=True)
    generate_all_sample_data()
