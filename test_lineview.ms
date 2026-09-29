-- test_lineview.ms : automated test for LineViewExporter core (3ds Max batch)
(
	-- declare before compile-time binding: these globals are created by fileIn below
	global LineView_ExportSVG
	global LV_ViewDef

	local repoDir = @"C:/Users/Penguin8n/.zcode/workspace/default/line-view-exporter/"
	local outSvg = repoDir + "test_output.svg"

	format "=== LineViewExporter automated test ===\n"

	-- 1) load the tool
	try ( fileIn (repoDir + "LineViewExporter.ms") ) catch ( format "[FAIL] fileIn threw: %\n" (getCurrentException() as string) )
	format "[1] fileIn done, LineView_ExportSVG defined: %\n" (LineView_ExportSVG != undefined)

	-- 2) build test scene
	delete objects
	local b1 = Box length:40 width:60 height:30 lengthsegs:2 widthsegs:3 heightsegs:2
	b1.name = "T_Box"
	local t1 = Teapot radius:18 segments:5
	t1.name = "T_Teapot"
	t1.pos = [90, 0, 0]
	local p1 = Plane length:30 width:30
	p1.name = "T_Plane"
	p1.pos = [-90, 0, 0]
	local c1 = Cylinder radius:10 height:50 sides:18 heightsegs:1
	c1.name = "T_Cyl18"
	c1.pos = [0, 110, 0]
	local s1 = Sphere radius:12 seg:16
	s1.name = "T_SphereStretched"
	s1.pos = [0, -110, 0]
	scale s1 [2, 1, 1]

	local objs = #(b1, t1, p1, c1, s1)
	format "[2] test scene built: % objects\n" objs.count

	-- 3) run the export core (3 views + hidden lines, A4 landscape)
	local vd = #(
		(LV_ViewDef name:"FRONT" right:[1,0,0] down:[0,0,-1] viewDir:[0,1,0] col:0 row:1 vis:#() hid:#()),
		(LV_ViewDef name:"RIGHT" right:[0,1,0] down:[0,0,-1] viewDir:[-1,0,0] col:1 row:1 vis:#() hid:#()),
		(LV_ViewDef name:"TOP" right:[1,0,0] down:[0,1,0] viewDir:[0,0,-1] col:0 row:0 vis:#() hid:#())
	)
	local res = LineView_ExportSVG objs vd true 30 0.5 false outSvg 1 undefined
	format "[3] result: %\n" res

	-- 4) verify output
	if doesFileExist outSvg then
	(
		local visTotal = 0
		local hidTotal = 0
		for v in vd do
		(
			local vc = 0
			for oseg in v.vis do vc += oseg.segs.count
			local hc = 0
			for oseg in v.hid do hc += oseg.segs.count
			visTotal += vc
			hidTotal += hc
			format "    % : % visible segs, % hidden segs\n" v.name vc hc
		)
		if visTotal > 100 and hidTotal > 10 then format "TEST PASS (visible=% hidden=%)\n" visTotal hidTotal
		else format "TEST FAIL - suspiciously few segments (visible=% hidden=%)\n" visTotal hidTotal
	)
	else format "TEST FAIL - output SVG not created\n"

	quitMax #noPrompt
)
