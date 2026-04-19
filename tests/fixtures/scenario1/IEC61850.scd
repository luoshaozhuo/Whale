<?xml version="1.0" encoding="UTF-8"?>
<SCL xmlns="http://www.iec.ch/61850/2003/SCL">

  <Header id="WF_2WTG" version="1.0"/>

  <Substation name="WF01">
    <VoltageLevel name="VL1">
      <Bay name="WTG01_Bay">
        <LNode iedName="WTG_01" ldInst="LD0" lnClass="LLN0" lnInst=""/>
      </Bay>
      <Bay name="WTG02_Bay">
        <LNode iedName="WTG_02" ldInst="LD0" lnClass="LLN0" lnInst=""/>
      </Bay>
    </VoltageLevel>
  </Substation>

  <Communication>
    <SubNetwork name="StationBus" type="8-MMS">
      <ConnectedAP iedName="WTG_01" apName="AP1">
        <Address>
          <P type="IP">192.168.1.101</P>
          <P type="PORT">102</P>
        </Address>
      </ConnectedAP>
      <ConnectedAP iedName="WTG_02" apName="AP1">
        <Address>
          <P type="IP">192.168.1.102</P>
          <P type="PORT">102</P>
        </Address>
      </ConnectedAP>
    </SubNetwork>
  </Communication>

  <!-- ================= WTG_01 ================= -->
  <IED name="WTG_01">
    <AccessPoint name="AP1">
      <Server>
        <LDevice inst="LD0">

          <LN0 lnClass="LLN0">
            <DataSet name="ds_meas">
              <FCDA ldInst="LD0" lnClass="MMXU" lnInst="1" doName="TotW" daName="mag.f"/>
              <FCDA ldInst="LD0" lnClass="WROT" lnInst="1" doName="Spd" daName="mag.f"/>
              <FCDA ldInst="LD0" lnClass="WMET" lnInst="1" doName="WS" daName="mag.f"/>
            </DataSet>
          </LN0>

          <LN lnClass="MMXU" inst="1"/>
          <LN lnClass="WROT" inst="1"/>
          <LN lnClass="WMET" inst="1"/>

        </LDevice>
      </Server>
    </AccessPoint>
  </IED>

  <!-- ================= WTG_02 ================= -->
  <IED name="WTG_02">
    <AccessPoint name="AP1">
      <Server>
        <LDevice inst="LD0">

          <LN0 lnClass="LLN0">
            <DataSet name="ds_meas">
              <FCDA ldInst="LD0" lnClass="MMXU" lnInst="1" doName="TotW" daName="mag.f"/>
              <FCDA ldInst="LD0" lnClass="WROT" lnInst="1" doName="Spd" daName="mag.f"/>
              <FCDA ldInst="LD0" lnClass="WMET" lnInst="1" doName="WS" daName="mag.f"/>
            </DataSet>
          </LN0>

          <LN lnClass="MMXU" inst="1"/>
          <LN lnClass="WROT" inst="1"/>
          <LN lnClass="WMET" inst="1"/>

        </LDevice>
      </Server>
    </AccessPoint>
  </IED>

</SCL>