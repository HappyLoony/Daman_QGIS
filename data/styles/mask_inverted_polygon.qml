<!DOCTYPE qgis PUBLIC 'http://mrcc.com/qgis.dtd' 'SYSTEM'>
<!--
  Mask Style - Inverted Polygon with Shapeburst Fill
  Source: AEAG Mask plugin (default_mask_style.qml)
  Purpose: Visual masking of areas outside polygon boundary

  Usage:
    layer.loadNamedStyle("data/styles/mask_inverted_polygon.qml")
    layer.triggerRepaint()

  Parameters:
    - invertedPolygonRenderer: Shows everything EXCEPT the polygon
    - ShapeburstFill: Gradient fill from border
    - blur_radius: 15 (soft edge)
    - max_distance: 5mm (gradient width)
    - color: 73,94,123,164 (blue-gray, 64% opacity)
    - gradient_color2: 255,255,255,173 (white, 68% opacity)
-->
<qgis version="3.40.5-Bratislava" styleCategories="Symbology">
  <renderer-v2 preprocessing="0" forceraster="0" symbollevels="0" enableorderby="0" type="invertedPolygonRenderer" referencescale="-1">
    <renderer-v2 forceraster="0" symbollevels="0" enableorderby="0" type="singleSymbol" referencescale="-1">
      <symbols>
        <symbol force_rhr="0" alpha="1" clip_to_extent="1" frame_rate="10" type="fill" name="0" is_animated="0">
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
          <layer enabled="1" class="ShapeburstFill" locked="0" pass="0" id="{mask-shapeburst-fill}">
            <Option type="Map">
              <!-- Blur radius for soft edge effect -->
              <Option value="15" type="QString" name="blur_radius"/>
              <!-- Main fill color: blue-gray with 64% opacity -->
              <Option value="73,94,123,164,rgb:0.28627450980392155,0.36862745098039218,0.4823529411764706,0.64313725490196083" type="QString" name="color"/>
              <!-- Gradient colors (not used with color_type=0) -->
              <Option value="0,0,255,255,rgb:0,0,1,1" type="QString" name="color1"/>
              <Option value="0,255,0,255,rgb:0,1,0,1" type="QString" name="color2"/>
              <!-- color_type: 0=simple two-color, 1=color ramp -->
              <Option value="0" type="QString" name="color_type"/>
              <Option value="ccw" type="QString" name="direction"/>
              <Option value="0" type="QString" name="discrete"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="distance_map_unit_scale"/>
              <Option value="MM" type="QString" name="distance_unit"/>
              <!-- Gradient end color: white with 68% opacity -->
              <Option value="255,255,255,173,rgb:1,1,1,0.67910276951247428" type="QString" name="gradient_color2"/>
              <Option value="0" type="QString" name="ignore_rings"/>
              <!-- Max distance for shapeburst effect (5mm from boundary) -->
              <Option value="5" type="QString" name="max_distance"/>
              <Option value="0,0" type="QString" name="offset"/>
              <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
              <Option value="MM" type="QString" name="offset_unit"/>
              <Option value="gradient" type="QString" name="rampType"/>
              <Option value="rgb" type="QString" name="spec"/>
              <!-- use_whole_shape: 0=use max_distance, 1=fill entire area -->
              <Option value="0" type="QString" name="use_whole_shape"/>
            </Option>
            <data_defined_properties>
              <Option type="Map">
                <Option value="" type="QString" name="name"/>
                <Option name="properties"/>
                <Option value="collection" type="QString" name="type"/>
              </Option>
            </data_defined_properties>
          </layer>
        </symbol>
      </symbols>
      <rotation/>
      <sizescale/>
      <data-defined-properties>
        <Option type="Map">
          <Option value="" type="QString" name="name"/>
          <Option name="properties"/>
          <Option value="collection" type="QString" name="type"/>
        </Option>
      </data-defined-properties>
    </renderer-v2>
    <data-defined-properties>
      <Option type="Map">
        <Option value="" type="QString" name="name"/>
        <Option name="properties"/>
        <Option value="collection" type="QString" name="type"/>
      </Option>
    </data-defined-properties>
  </renderer-v2>
  <selection mode="Default">
    <selectionColor invalid="1"/>
    <selectionSymbol>
      <symbol force_rhr="0" alpha="1" clip_to_extent="1" frame_rate="10" type="fill" name="" is_animated="0">
        <data_defined_properties>
          <Option type="Map">
            <Option value="" type="QString" name="name"/>
            <Option name="properties"/>
            <Option value="collection" type="QString" name="type"/>
          </Option>
        </data_defined_properties>
        <layer enabled="1" class="SimpleFill" locked="0" pass="0" id="{mask-selection-fill}">
          <Option type="Map">
            <Option value="3x:0,0,0,0,0,0" type="QString" name="border_width_map_unit_scale"/>
            <Option value="0,0,255,255,rgb:0,0,1,1" type="QString" name="color"/>
            <Option value="bevel" type="QString" name="joinstyle"/>
            <Option value="0,0" type="QString" name="offset"/>
            <Option value="3x:0,0,0,0,0,0" type="QString" name="offset_map_unit_scale"/>
            <Option value="MM" type="QString" name="offset_unit"/>
            <Option value="35,35,35,255,rgb:0.13725490196078433,0.13725490196078433,0.13725490196078433,1" type="QString" name="outline_color"/>
            <Option value="solid" type="QString" name="outline_style"/>
            <Option value="0.26" type="QString" name="outline_width"/>
            <Option value="MM" type="QString" name="outline_width_unit"/>
            <Option value="solid" type="QString" name="style"/>
          </Option>
          <data_defined_properties>
            <Option type="Map">
              <Option value="" type="QString" name="name"/>
              <Option name="properties"/>
              <Option value="collection" type="QString" name="type"/>
            </Option>
          </data_defined_properties>
        </layer>
      </symbol>
    </selectionSymbol>
  </selection>
  <blendMode>0</blendMode>
  <featureBlendMode>0</featureBlendMode>
  <layerGeometryType>2</layerGeometryType>
</qgis>
