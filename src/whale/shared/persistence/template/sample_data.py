"""全套风电场样本数据生成脚本.

大唐集团 → 华北分公司 → 张北风电场
3 个 IED 采集模板，30 台风机共用风机模板
GB/T 30966.2 全量测点覆盖
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy.orm import Session

from whale.shared.persistence.orm import (
    AcquisitionTask,
    AssetBOM,
    AssetInstance,
    AssetType,
    BladeModel,
    BMSModel,
    BatteryCellModel,
    BatterySystemModel,
    CDCDict,
    CombinerBoxModel,
    ComponentInstance,
    ComponentType,
    DO,
    DOState,
    FCDict,
    GearboxModel,
    GeneratorModel,
    IED,
    LD,
    LN,
    Organization,
    PCSModel,
    PVInverterModel,
    PVPanelModel,
    PitchSystemModel,
    SVGModel,
    StateSnapshotOutbox,
    ThermalManagementModel,
    TowerModel,
    TrackerModel,
    TransformerModel,
    WindTurbineModel,
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

        asset_types = _create_asset_types(session)
        component_types = _create_component_types(session)
        session.flush()
        print(f"✓ 类型: {len(asset_types)} 资产 + {len(component_types)} 部件")

        asset_models = _create_asset_models(session, asset_types)
        component_models = _create_component_models(session, component_types)
        session.flush()
        _create_bom(session, asset_types, asset_models, component_types, component_models)
        _create_cdc_fc_dicts(session)
        session.flush()
        print(f"✓ 型号: {len(asset_models)} 资产 + {len(component_models)} 部件 + BOM + CDC/FC")

        assets = _create_asset_instances(session, asset_types, asset_models, plant)
        session.flush()
        turbines = assets["turbines"]
        print(f"✓ 资产实例: {len(turbines)} 台风机 + 箱变/逆变器/储能/SVG/气象站/光伏")

        _create_component_instances(session, component_types, component_models, turbines)
        session.flush()
        print(f"✓ 部件实例: 每台风机 5 部件 × {TURBINE_COUNT} 台")

        ied, do_count = _create_ied_template(session, ALL_LOGICAL_NODES, AT_WIND_TURBINE)
        met_ied, met_do_count = _create_met_ied_template(session, AT_MET_STATION)
        sub_ied, sub_do_count = _create_substation_ied_template(session, AT_SUBSTATION)
        session.flush()
        print(f"✓ IED 模板: 3 个, 共 {do_count + met_do_count + sub_do_count} DO")

        tasks = _create_acquisition_tasks(session, turbines, ied, met_ied, sub_ied)
        session.flush()
        print(f"✓ 采集任务: {len(tasks)} 个")

        vs_count = _create_do_states(session)
        outbox_count = _create_outbox_samples(session)
        session.flush()
        print(f"✓ DO 状态: {vs_count} / 发件箱: {outbox_count}")

        session.commit()
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
# 2-3. 类型
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
        (CT_BLADE, "风机叶片，捕获风能转换为旋转动能，材料为玻璃纤维/碳纤维增强复合材料"),
        (CT_TOWER, "风机塔筒，支撑机舱至轮毂设计高度，钢制锥筒或混合式结构"),
        (CT_GEARBOX, "齿轮增速箱，将风轮低速大扭矩转换为发电机所需高速"),
        (CT_GENERATOR, "发电机，将机械能转换为电能，双馈异步或永磁直驱"),
        (CT_PITCH, "变桨系统，调节叶片桨距角以控制转速和功率输出"),
        (CT_ROTOR, "叶轮总成，含轮毂/导流罩/叶片连接法兰"),
        (CT_NACELLE, "机舱，容纳齿轮箱/发电机/变流器/偏航驱动等核心部件"),
        (CT_CONVERTER, "变流器，AC-DC-AC 电力电子变换，实现变速恒频"),
        (CT_CONTROL, "主控系统，风机运行逻辑控制/状态监测/故障保护/通信管理"),
        (CT_YAW, "偏航系统，根据风向信号驱动机舱转动使叶轮对风"),
        (CT_MAIN_SHAFT, "主轴，传递叶轮扭矩至齿轮箱输入轴，锻钢制造"),
        (CT_BRAKE, "制动系统，含高速轴制动盘/偏航制动器/液压站"),
        (CT_POWER_MODULE, "IGBT 功率模块，变流器核心电力电子开关单元"),
        (CT_COOLING, "散热系统，液冷/风冷方式为变流器和发电机散热"),
        (CT_CONTROL_BOARD, "控制板，DSP/ARM 主控电路板，运行控制算法与通信协议栈"),
        (CT_TRACKER, "光伏跟踪支架，单轴或双轴跟踪太阳方位以提升发电量"),
        (CT_COMBINER, "光伏汇流箱，将多路光伏组串直流汇入逆变器，含熔断/防雷"),
        (CT_BATTERY_CELL, "锂电池单体，磷酸铁锂/三元/钠离子等化学体系，方形铝壳/圆柱/软包"),
        (CT_BMS, "电池管理系统，采集电芯电压/温度/SOC/SOH，实施均衡与保护策略"),
        (CT_THERMAL, "储能热管理系统，液冷/风冷方式控制电池簇工作温度"),
        (CT_TRANSFORMER_COMP, "变压器铁芯与绕组组件，硅钢片叠装铁芯+铜/铝绕组"),
        (CT_CIRCUIT_BREAKER, "高压断路器，SF6/真空灭弧，开断短路电流保护"),
    ]
    result = {}
    for name, desc in types:
        ct = ComponentType(component_type_name=name, description=desc)
        session.add(ct); result[name] = ct
    return result


# ══════════════════════════════════════════════════════════════════════
# 4-5. 型号
# ══════════════════════════════════════════════════════════════════════

def _create_asset_models(session: Session, at: dict) -> dict:
    def _add(m): session.add(m); return m
    wt = _add(WindTurbineModel(
        asset_type_id=at[AT_WIND_TURBINE].asset_type_id,
        model_name="金风GW121/2500", rated_power_kw=2500.0, cut_in_wind_speed_m_s=3.0,
        cut_out_wind_speed_m_s=25.0, rated_wind_speed_m_s=12.0, survival_wind_speed_m_s=59.5,
        rotor_diameter_m=121.0, hub_height_m=90.0, rated_voltage_v=690, frequency_hz=50.0,
        min_operating_temp_c=-30.0, max_operating_temp_c=40.0, survival_min_temp_c=-40.0,
        survival_max_temp_c=50.0, design_life_year=20, wind_class="IEC IIA", manufacturer="金风科技",
    ))
    pv_inv = _add(PVInverterModel(
        asset_type_id=at[AT_INVERTER].asset_type_id, model_name="华为SUN2000-300KTL-H0",
        rated_power_kw=300.0, max_input_voltage_v=1500, mppt_voltage_min_v=500,
        mppt_voltage_max_v=1500, rated_output_voltage_v=800, rated_output_frequency_hz=50.0,
        max_efficiency=0.99, mppt_count=8, protection_rating="IP66",
        operating_temp_min_c=-25.0, operating_temp_max_c=60.0, manufacturer="华为",
    ))
    pv_panel = _add(PVPanelModel(
        asset_type_id=at[AT_PV_PANEL].asset_type_id, model_name="隆基LR5-72HBD-540M",
        peak_power_wp=540.0, open_circuit_voltage_v=49.6, short_circuit_current_a=13.86,
        voltage_at_pmax_v=41.7, current_at_pmax_a=12.95, module_efficiency=0.212,
        temperature_coefficient_pmax=-0.34, cell_type="单晶P型PERC", cell_count=144,
        dimensions_mm="2256×1133×35", weight_kg=28.5, manufacturer="隆基绿能",
    ))
    pcs = _add(PCSModel(
        asset_type_id=at[AT_PCS].asset_type_id, model_name="阳光电源SC2000UD-MV",
        rated_power_kw=2000.0, rated_apparent_power_kva=2200.0, dc_voltage_min_v=600,
        dc_voltage_max_v=1500, ac_rated_voltage_v=690, ac_rated_frequency_hz=50.0,
        max_efficiency=0.987, response_time_ms=50, cooling_method="液冷",
        operating_temp_min_c=-30.0, operating_temp_max_c=55.0, protection_rating="IP54",
        manufacturer="阳光电源",
    ))
    battery = _add(BatterySystemModel(
        asset_type_id=at[AT_BATTERY].asset_type_id, model_name="宁德时代EnerOne-3727",
        rated_energy_kwh=3727.0, rated_power_kw=1864.0, nominal_voltage_v=1331.0,
        operating_voltage_min_v=1165.0, operating_voltage_max_v=1498.0, chemistry_type="LFP",
        max_charge_c_rate=1.0, max_discharge_c_rate=1.0, round_trip_efficiency=0.89,
        cycle_life=12000, operating_temp_min_c=-20.0, operating_temp_max_c=45.0, manufacturer="宁德时代",
    ))
    transformer = _add(TransformerModel(
        asset_type_id=at[AT_TRANSFORMER].asset_type_id, model_name="特变电工SZ11-50000/110",
        rated_capacity_kva=50000.0, primary_voltage_kv=110.0, secondary_voltage_kv=35.0,
        vector_group="YNd11", impedance_percent=10.5, cooling_method="ONAN",
        tap_changer_type="有载调压", manufacturer="特变电工",
    ))
    svg = _add(SVGModel(
        asset_type_id=at[AT_SVG].asset_type_id, model_name="思源电气QNSVG-20/35",
        rated_capacity_kvar=20000.0, rated_voltage_kv=35.0, rated_frequency_hz=50.0,
        response_time_ms=5, cooling_method="风冷", harmonic_compensation="2~25次",
        operating_temp_min_c=-25.0, operating_temp_max_c=45.0, manufacturer="思源电气",
    ))
    return {"wt": wt, "pv_inv": pv_inv, "pv_panel": pv_panel, "pcs": pcs,
            "battery": battery, "transformer": transformer, "svg": svg}


def _create_component_models(session: Session, ct: dict) -> dict:
    def _add(m): session.add(m); return m
    blade = _add(BladeModel(
        component_type_id=ct[CT_BLADE].component_type_id, model_name="LM 61.5 P2",
        length_m=61.5, weight_kg=18500.0, material="玻璃纤维增强环氧树脂",
        aerodynamic_profile="NACA63-4xx系列", suitable_rotor_diameter_m=121.0,
        design_life_year=20, manufacturer="LM Wind Power",
    ))
    tower = _add(TowerModel(
        component_type_id=ct[CT_TOWER].component_type_id, model_name="ST-90/2500",
        hub_height_m=90.0, top_diameter_m=3.2, bottom_diameter_m=4.3, sections_count=4,
        material="Q420ME钢材", suitable_power_kw=2500.0, manufacturer="天顺风能",
    ))
    gearbox = _add(GearboxModel(
        component_type_id=ct[CT_GEARBOX].component_type_id, model_name="Winergy PEAB 4440",
        rated_power_kw=2800.0, ratio=118.0, input_rpm=15.0, output_rpm=1770.0,
        stages_count=3, weight_kg=32000.0, design_life_year=20, manufacturer="Winergy",
    ))
    generator = _add(GeneratorModel(
        component_type_id=ct[CT_GENERATOR].component_type_id, model_name="ABB AMK 500L6L",
        rated_power_kw=2600.0, rated_voltage_v=690, rated_rpm=1800, rated_frequency_hz=50.0,
        efficiency=0.971, cooling_type="IC616", insulation_class="H", protection_rating="IP54",
        generator_type="双馈异步", manufacturer="ABB",
    ))
    pitch = _add(PitchSystemModel(
        component_type_id=ct[CT_PITCH].component_type_id, model_name="SSB PE3-290",
        actuation_type="电动", response_time_ms=100, max_pitch_rate_deg_s=8.0,
        redundancy="3轴独立+超级电容后备", emergency_stop_time_ms=3000, manufacturer="SSB Wind",
    ))
    tracker = _add(TrackerModel(
        component_type_id=ct[CT_TRACKER].component_type_id, model_name="中信博天际单轴",
        tracking_type="单轴平单轴", tracking_range_deg="-55°~+55°", suitable_module_count=90,
        drive_type="电动推杆", wind_resistance_m_s=45.0, manufacturer="中信博",
    ))
    combiner = _add(CombinerBoxModel(
        component_type_id=ct[CT_COMBINER].component_type_id, model_name="许继PVA-16H",
        input_string_count=16, max_input_voltage_v=1500, max_output_current_a=250.0,
        protection_rating="IP65", has_monitoring=True, manufacturer="许继电气",
    ))
    cell = _add(BatteryCellModel(
        component_type_id=ct[CT_BATTERY_CELL].component_type_id, model_name="CATL-LFP-280Ah",
        chemistry="LFP", nominal_voltage_v=3.2, capacity_ah=280.0, energy_density_wh_kg=165.0,
        max_charge_c_rate=1.0, max_discharge_c_rate=1.0, cycle_life=12000,
        operating_temp_min_c=-20.0, operating_temp_max_c=55.0, form_factor="方形铝壳",
        manufacturer="宁德时代",
    ))
    bms = _add(BMSModel(
        component_type_id=ct[CT_BMS].component_type_id, model_name="科工BMS-LFP-3S",
        topology="三级架构（BMU/BCMU/BAMS）", max_cell_series_count=320,
        balancing_method="主动均衡", balancing_current_a=2.0,
        communication_protocol="CAN 2.0B + Modbus RTU", voltage_accuracy_mv=5.0,
        temperature_accuracy_c=1.0, manufacturer="科工电子",
    ))
    thermal = _add(ThermalManagementModel(
        component_type_id=ct[CT_THERMAL].component_type_id, model_name="英维克EC-X20",
        cooling_type="液冷", cooling_capacity_kw=20.0, heating_capacity_kw=10.0,
        operating_temp_min_c=-30.0, operating_temp_max_c=55.0, coolant_type="50%乙二醇溶液",
        noise_level_db=65.0, manufacturer="英维克",
    ))
    return {"blade": blade, "tower": tower, "gearbox": gearbox, "generator": generator,
            "pitch": pitch, "tracker": tracker, "combiner": combiner,
            "cell": cell, "bms": bms, "thermal": thermal}


# ══════════════════════════════════════════════════════════════════════
# 6. BOM + CDC/FC
# ══════════════════════════════════════════════════════════════════════

def _create_bom(session: Session, at: dict, am: dict, ct: dict, cm: dict) -> None:
    for comp_type_id, comp_model_id, qty in [
        (ct[CT_BLADE].component_type_id, cm["blade"].model_id, 3),
        (ct[CT_TOWER].component_type_id, cm["tower"].model_id, 1),
        (ct[CT_GEARBOX].component_type_id, cm["gearbox"].model_id, 1),
        (ct[CT_GENERATOR].component_type_id, cm["generator"].model_id, 1),
        (ct[CT_PITCH].component_type_id, cm["pitch"].model_id, 1),
    ]:
        session.add(AssetBOM(
            asset_type_id=at[AT_WIND_TURBINE].asset_type_id, asset_model_id=am["wt"].model_id,
            component_type_id=comp_type_id, component_model_id=comp_model_id, quantity=qty,
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
# 7. 资产实例
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
# 8. 部件实例
# ══════════════════════════════════════════════════════════════════════

def _create_component_instances(session: Session, ct: dict, cm: dict,
                                 turbines: list[AssetInstance]) -> None:
    install_base = date(2024, 6, 1)
    for i, turbine in enumerate(turbines):
        for b in range(1, 4):
            session.add(ComponentInstance(
                component_type_id=ct[CT_BLADE].component_type_id, component_model_id=cm["blade"].model_id,
                asset_instance_id=turbine.asset_instance_id,
                installation_date=install_base + timedelta(days=i * 7)))
        for comp_type, comp_model in [
            (ct[CT_TOWER], cm["tower"]), (ct[CT_GEARBOX], cm["gearbox"]),
            (ct[CT_GENERATOR], cm["generator"]), (ct[CT_PITCH], cm["pitch"]),
        ]:
            session.add(ComponentInstance(
                component_type_id=comp_type.component_type_id, component_model_id=comp_model.model_id,
                asset_instance_id=turbine.asset_instance_id,
                installation_date=install_base + timedelta(days=i * 7)))


# ══════════════════════════════════════════════════════════════════════
# 9. IED 模板
# ══════════════════════════════════════════════════════════════════════

def _create_ied_template(session: Session, all_logical_nodes: list, ld_name: str) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    do_count = 0
    for node_def in all_logical_nodes:
        ln = LN(ln_name=node_def.name, ld_id=ld.ld_id, description=node_def.desc)
        session.add(ln); session.flush()
        for field in node_def.fields:
            session.add(DO(
                ln_id=ln.ln_id, do_name=field.key,
                cdc=field.cdc, fc="MX" if field.cdc == "MV" else "ST",
                data_type=field.data_type,
                unit=field.unit if field.unit else None,
                constraint_expr=_constraint_for(field),
                display_name=field.desc,
            ))
            do_count += 1
    return ied, do_count


def _create_met_ied_template(session: Session, ld_name: str) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    ln = LN(ln_name="WMET", ld_id=ld.ld_id, description="气象信息")
    session.add(ln); session.flush()
    do_count = 0
    for key, unit, desc, constraint in [
        ("WSpd", "m/s", "风速", "BETWEEN 0 75"), ("WSpdMax", "m/s", "最大风速", "BETWEEN 0 75"),
        ("WSpdMin", "m/s", "最小风速", "BETWEEN 0 75"), ("Wdir", "deg", "风向", "BETWEEN 0 360"),
        ("Tmp", "deg C", "环境温度", "BETWEEN -40 60"), ("Hum", "%", "相对湿度", "BETWEEN 0 100"),
        ("Press", "hPa", "大气压力", "BETWEEN 500 1100"), ("Rain", "mm", "降水量", ">= 0"),
        ("Rad", "W/m²", "太阳辐照度", "BETWEEN 0 1500"),
    ]:
        session.add(DO(ln_id=ln.ln_id, do_name=key, cdc="MV", fc="MX",
                       data_type="Double", unit=unit, constraint_expr=constraint, display_name=desc))
        do_count += 1
    return ied, do_count


def _create_substation_ied_template(session: Session, ld_name: str) -> tuple[IED, int]:
    ied = IED(ied_name=f"IED_{ld_name}_OPCUA", protocol_type="OPC_UA")
    session.add(ied); session.flush()
    ld = LD(ld_name=ld_name, ied_id=ied.ied_id)
    session.add(ld); session.flush()
    ln = LN(ln_name="MMXU", ld_id=ld.ld_id, description="测量单元")
    session.add(ln); session.flush()
    do_count = 0
    for key, unit, desc, constraint in [
        ("PhV", "V", "相电压", "BETWEEN 0 126000"), ("A", "A", "相电流", "BETWEEN 0 5000"),
        ("W", "kW", "有功功率", "BETWEEN -50000 150000"), ("VAr", "kVAr", "无功功率", "BETWEEN -20000 20000"),
        ("Hz", "Hz", "频率", "BETWEEN 49 51"), ("PF", "", "功率因数", "BETWEEN -1 1"),
    ]:
        session.add(DO(ln_id=ln.ln_id, do_name=key, cdc="MV", fc="MX",
                       data_type="Double", unit=unit, constraint_expr=constraint, display_name=desc))
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
# 10. 采集任务
# ══════════════════════════════════════════════════════════════════════

def _create_acquisition_tasks(session: Session, turbines: list, ied: IED,
                               met_ied: IED, sub_ied: IED) -> list:
    tasks = []
    for i, t in enumerate(turbines):
        task = AcquisitionTask(
            task_name=f"task_{t.asset_code}", asset_instance_id=t.asset_instance_id,
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
        asset_id = session.query(AssetInstance.asset_instance_id).filter(
            AssetInstance.asset_code == asset_code).scalar()
        session.add(AcquisitionTask(
            task_name=name, asset_instance_id=asset_id, ied_id=ied_obj.ied_id,
            protocol_type="OPC_UA", endpoint=endpoint, sampling_interval_ms=interval,
            acquisition_mode=mode, priority=1))
        tasks.append(None)
    return tasks


# ══════════════════════════════════════════════════════════════════════
# 11. DO 初始状态
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
            IED.ied_name == f"IED_{AT_WIND_TURBINE}_OPCUA").limit(50).all()
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
        for do in session.query(DO).join(DO.ln).join(LN.ld).join(LD.ied).filter(IED.ied_name == f"IED_{AT_MET_STATION}_OPCUA").all():
            session.add(DOState(task_id=met_task.task_id, asset_instance_id=met_asset.asset_instance_id,
                                do_id=do.do_id, value=met_vals.get(do.display_name or "", "0.0"),
                                source_observed_at=now))
            count += 1
    return count


# ══════════════════════════════════════════════════════════════════════
# 12. 发件箱
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


if __name__ == "__main__":
    generate_all_sample_data()
