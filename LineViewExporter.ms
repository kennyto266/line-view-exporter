/*
	LineViewExporter.ms
	-------------------
	Exports orthographic line views (Front / Back / Left / Right / Top / Bottom)
	of scene geometry to an SVG sheet that Adobe Illustrator opens as fully
	editable vector paths (one named group per view, one path per object).

	Quick use:  drag this file into a 3ds Max viewport, pick options, EXPORT.
	Install:    Customize > Customize User Interface, category "LineView",
	            macro "LineViewToSVG" -> toolbar button / menu / hotkey.

	Notes:
	- If nothing is selected, all visible, unfrozen geometry is exported.
	- The last line of this file auto-opens the dialog when the file is
	  dragged into Max. Remove it if you place this file in a startup folder.
*/

macroScript LineViewToSVG
	category:"LineView"
	tooltip:"Export Front/Side/Top line views to SVG for Illustrator"
	buttonText:"LineView to SVG"
(
	/* ---------- small helpers ---------- */

	fn fmt3 v = formattedPrint v format:"0.3f"

	fn repAll s old new =
	(
		while (findString s old) != undefined do s = substitute s old new
		s
	)

	fn xmlEscape s =
	(
		s = repAll s "&" "&amp;"
		s = repAll s "<" "&lt;"
		s = repAll s ">" "&gt;"
		s = repAll s "\"" "&quot;"
		s = repAll s "'" "&apos;"
		s
	)

	struct BBox2 (minX, minY, maxX, maxY)

	fn newBBox = BBox2 minX:1.0e30 minY:1.0e30 maxX:-1.0e30 maxY:-1.0e30

	fn bboxAdd bb p =
	(
		if p.x < bb.minX then bb.minX = p.x
		if p.y < bb.minY then bb.minY = p.y
		if p.x > bb.maxX then bb.maxX = p.x
		if p.y > bb.maxY then bb.maxY = p.y
	)

	struct ObjSegs (name, segs)

	/* name = SVG group name, right/down = screen axes in world space,
	   viewDir = viewing direction, col/row = sheet grid position */
	struct ViewDef (name, right, down, viewDir, col, row, vis, hid, bb, ox, oy, sc)

	/* Snapshot an object into world space and collect edge/face data.
	   Returns #(worldVerts, faceNormals, edgeVerts, edgeFaces) or undefined. */
	fn buildWorldData obj =
	(
		local tmp = undefined
		local res = undefined
		try
		(
			tmp = snapshot obj
			convertToPoly tmp
			local numV = polyop.getNumVerts tmp
			local wverts = #()
			for i = 1 to numV do append wverts ((polyop.getVert tmp i) * tmp.transform)
			local numF = polyop.getNumFaces tmp
			local faceN = #()
			for i = 1 to numF do
			(
				local fv = polyop.getFaceVerts tmp i
				local a = wverts[fv[1]]
				local b = wverts[fv[2]]
				local c = wverts[fv[3]]
				append faceN (normalize (cross (b - a) (c - a)))
			)
			local numE = polyop.getNumEdges tmp
			local edgesV = #()
			local edgesF = #()
			for i = 1 to numE do
			(
				append edgesV (polyop.getEdgeVerts tmp i)
				append edgesF (polyop.getEdgeFaces tmp i)
			)
			res = #(wverts, faceN, edgesV, edgesF)
		)
		catch ( res = undefined )
		if tmp != undefined do ( try ( delete tmp ) catch ( false ) )
		res
	)

	/* ---------- UI ---------- */

	rollout roLV "Line View -> SVG (Illustrator)" width:330
	(
		group "Views"
		(
			checkbox chkFront "Front" checked:true across:3
			checkbox chkRight "Right" checked:true
			checkbox chkTop "Top" checked:true
			checkbox chkBack "Back" across:3
			checkbox chkLeft "Left"
			checkbox chkBottom "Bottom"
		)
		group "Line extraction"
		(
			spinner spCrease "Crease angle (deg): " range:[0,90,30] type:#integer fieldwidth:44 align:#right
			spinner spWeight "Stroke weight (pt): " range:[0.05,5.0,0.5] scale:0.05 fieldwidth:44 align:#right
			checkbox chkHidden "Include hidden edges (dashed grey)"
			checkbox chkFlip "Flip facing test (if views look inverted)"
		)
		group "Sheet"
		(
			dropdownlist ddlPage items:#("A4 landscape (fit)", "A3 landscape (fit)", "A4 portrait (fit)", "No fit - 1 max unit = 1 pt") selection:1
		)
		group "Output"
		(
			edittext etPath "File:" text:((getDir #export) + "\\line_views.svg") fieldwidth:250
			button btnBrowse "Browse..." width:90 align:#left
			button btnExport "EXPORT LINE VIEWS" width:170 height:32
			progressbar pbMain value:0 color:(color 90 160 255)
			label lblInfo "No selection = all visible geometry" align:#left
		)

		on btnBrowse pressed do
		(
			local p = getSaveFileName filename:etPath.text types:"SVG file (*.svg)|*.svg|All files (*.*)|*.*|"
			if p != undefined do etPath.text = p
		)

		on btnExport pressed do
		(
			local viewDefs = #()
			if chkFront.checked do append viewDefs (ViewDef name:"FRONT" right:[1,0,0] down:[0,0,-1] viewDir:[0,1,0] col:0 row:1 vis:#() hid:#())
			if chkBack.checked do append viewDefs (ViewDef name:"BACK" right:[-1,0,0] down:[0,0,-1] viewDir:[0,-1,0] col:2 row:1 vis:#() hid:#())
			if chkRight.checked do append viewDefs (ViewDef name:"RIGHT" right:[0,1,0] down:[0,0,-1] viewDir:[-1,0,0] col:1 row:1 vis:#() hid:#())
			if chkLeft.checked do append viewDefs (ViewDef name:"LEFT" right:[0,-1,0] down:[0,0,-1] viewDir:[1,0,0] col:-1 row:1 vis:#() hid:#())
			if chkTop.checked do append viewDefs (ViewDef name:"TOP" right:[1,0,0] down:[0,1,0] viewDir:[0,0,-1] col:0 row:0 vis:#() hid:#())
			if chkBottom.checked do append viewDefs (ViewDef name:"BOTTOM" right:[1,0,0] down:[0,-1,0] viewDir:[0,0,1] col:0 row:2 vis:#() hid:#())

			if viewDefs.count == 0 then messageBox "Enable at least one view."
			else
			(
				local objs = #()
				if selection.count > 0 then
					objs = for o in selection where isKindOf o GeometryClass collect o
				else
					objs = for o in geometry where (isKindOf o GeometryClass) and (not o.isHiddenInVpt) and (not o.isFrozen) collect o

				if objs.count == 0 then messageBox "No geometry to export.\nSelect some objects, or make scene geometry visible."
				else
				(
					local filePath = etPath.text
					if ((toLower (getFilenameType filePath)) != ".svg") do filePath = filePath + ".svg"

					local includeHidden = chkHidden.checked
					local creaseRad = spCrease.value * pi / 180.0
					local fc = if chkFlip.checked then -1.0 else 1.0

					local t0 = timestamp()
					local failObjs = #()
					local objData = #()
					pbMain.value = 1

					with redraw off
					(
						undo off
						(
							-- pass 1: bake world-space topology per object
							for i = 1 to objs.count do
							(
								local d = buildWorldData objs[i]
								if d == undefined then append failObjs objs[i].name
								else append objData #(objs[i].name, d)
								pbMain.value = 50.0 * i / objs.count
								windows.processPostedMessages()
							)

							-- pass 2: classify + project edges for every view
							local totalWork = amax 1 (objData.count * viewDefs.count)
							local wi = 0
							for od in objData do
							(
								local nm = od[1]
								local wverts = od[2][1]
								local faceN = od[2][2]
								local edgesV = od[2][3]
								local edgesF = od[2][4]
								for vd in viewDefs do
								(
									local vs = #()
									local hs = #()
									for e = 1 to edgesV.count do
									(
										local ef = edgesF[e]
										local n1 = faceN[ef[1]]
										local c1 = (fc * (dot n1 vd.viewDir)) < 0.0
										local c2 = false
										if ef.count > 1 do c2 = (fc * (dot faceN[ef[2]] vd.viewDir)) < 0.0
										local visE = false
										local hidE = false
										if ef.count == 1 then
										(
											visE = c1
											if includeHidden do hidE = (not c1)
										)
										else
										(
											if c1 != c2 then visE = true
											else if c1 then
											(
												local dp = amax -1.0 (amin 1.0 (dot n1 faceN[ef[2]]))
												visE = (acos dp) > creaseRad
											)
											else if includeHidden then
											(
												local dp = amax -1.0 (amin 1.0 (dot n1 faceN[ef[2]]))
												hidE = (acos dp) > creaseRad
											)
										)
										if visE or hidE do
										(
											local ev = edgesV[e]
											local p1 = wverts[ev[1]]
											local p2 = wverts[ev[2]]
											if visE do append vs #([dot p1 vd.right, dot p1 vd.down], [dot p2 vd.right, dot p2 vd.down])
											if hidE do append hs #([dot p1 vd.right, dot p1 vd.down], [dot p2 vd.right, dot p2 vd.down])
										)
									)
									append vd.vis (ObjSegs name:nm segs:vs)
									if includeHidden do append vd.hid (ObjSegs name:nm segs:hs)
									wi += 1
									pbMain.value = 50.0 + 50.0 * wi / totalWork
									windows.processPostedMessages()
								)
							)

							-- per-view bounding boxes
							for vd in viewDefs do
							(
								local bb = newBBox()
								for oseg in vd.vis do for s in oseg.segs do ( bboxAdd bb s[1]; bboxAdd bb s[2] )
								if includeHidden do for oseg in vd.hid do for s in oseg.segs do ( bboxAdd bb s[1]; bboxAdd bb s[2] )
								vd.bb = bb
							)

							-- sheet layout (third-angle style grid)
							local pageMode = ddlPage.selection
							local m = 24.0
							local gap = 20.0
							local pad = 8.0
							local labelH = 16.0
							local pageW = 0.0
							local pageH = 0.0
							local colMin = 999999
							local colMax = -999999
							local rowMin = 999999
							local rowMax = -999999
							for vd in viewDefs do
							(
								colMin = amin colMin vd.col
								colMax = amax colMax vd.col
								rowMin = amin rowMin vd.row
								rowMax = amax rowMax vd.row
							)
							local ncols = colMax - colMin + 1
							local nrows = rowMax - rowMin + 1
							local cellW = 0.0
							local cellH = 0.0
							if pageMode == 4 then
							(
								local maxW = 1.0e-6
								local maxH = 1.0e-6
								for vd in viewDefs do
								(
									maxW = amax maxW (vd.bb.maxX - vd.bb.minX)
									maxH = amax maxH (vd.bb.maxY - vd.bb.minY)
								)
								cellW = maxW + 2 * pad
								cellH = maxH + 2 * pad + labelH
								pageW = 2 * m + ncols * cellW + (ncols - 1) * gap
								pageH = 2 * m + nrows * cellH + (nrows - 1) * gap
							)
							else
							(
								case pageMode of
								(
									1: ( pageW = 842.0; pageH = 595.0 )
									2: ( pageW = 1191.0; pageH = 842.0 )
									default: ( pageW = 595.0; pageH = 842.0 )
								)
								cellW = (pageW - 2 * m - (ncols - 1) * gap) / ncols
								cellH = (pageH - 2 * m - (nrows - 1) * gap) / nrows
							)
							local sc = 1.0
							if pageMode != 4 then
							(
								sc = 1.0e30
								for vd in viewDefs do
								(
									local w = amax 1.0e-6 (vd.bb.maxX - vd.bb.minX)
									local h = amax 1.0e-6 (vd.bb.maxY - vd.bb.minY)
									sc = amin sc (amin ((cellW - 2 * pad) / w) ((cellH - 2 * pad - labelH) / h))
								)
							)
							for vd in viewDefs do
							(
								local w = (vd.bb.maxX - vd.bb.minX) * sc
								local h = (vd.bb.maxY - vd.bb.minY) * sc
								local cx = m + (vd.col - colMin) * (cellW + gap)
								local cy = m + (vd.row - rowMin) * (cellH + gap)
								vd.sc = sc
								vd.ox = cx + (cellW - w) / 2.0 - vd.bb.minX * sc
								vd.oy = cy + (cellH - labelH - h) / 2.0 - vd.bb.minY * sc
							)

							-- write SVG
							local f = createFile filePath
							if f == undefined then messageBox ("Cannot write file:\n" + filePath)
							else
							(
								try
								(
									local strokeW = spWeight.value
									local hiddenW = strokeW * 0.7
									format "<?xml version='1.0' encoding='UTF-8'?>\n" to:f
									format "<svg xmlns='http://www.w3.org/2000/svg' width='%' height='%' viewBox='0 0 % %'>\n" (fmt3 pageW) (fmt3 pageH) (fmt3 pageW) (fmt3 pageH) to:f
									for vd in viewDefs do
									(
										format "<g id='%' fill='none' stroke='#000000' stroke-width='%' stroke-linecap='round' stroke-linejoin='round'>\n" vd.name (fmt3 strokeW) to:f
										for oseg in vd.vis where oseg.segs.count > 0 do
										(
											format "<path id='%' d='" (xmlEscape oseg.name) to:f
											for s in oseg.segs do
												format "M% % L% % " (fmt3 (s[1].x * vd.sc + vd.ox)) (fmt3 (s[1].y * vd.sc + vd.oy)) (fmt3 (s[2].x * vd.sc + vd.ox)) (fmt3 (s[2].y * vd.sc + vd.oy)) to:f
											format "'/>\n" to:f
										)
										format "</g>\n" to:f
										if includeHidden do
										(
											format "<g id='%' fill='none' stroke='#999999' stroke-width='%' stroke-dasharray='3,2' stroke-linecap='round'>\n" (vd.name + "_hidden") (fmt3 hiddenW) to:f
											for oseg in vd.hid where oseg.segs.count > 0 do
											(
												format "<path id='%' d='" (xmlEscape (oseg.name + "_hid")) to:f
												for s in oseg.segs do
													format "M% % L% % " (fmt3 (s[1].x * vd.sc + vd.ox)) (fmt3 (s[1].y * vd.sc + vd.oy)) (fmt3 (s[2].x * vd.sc + vd.ox)) (fmt3 (s[2].y * vd.sc + vd.oy)) to:f
												format "'/>\n" to:f
											)
											format "</g>\n" to:f
										)
										local lx = m + (vd.col - colMin) * (cellW + gap) + cellW / 2.0
										local ly = m + (vd.row - rowMin) * (cellH + gap) + cellH - 5.0
										format "<text x='%' y='%' font-family='Arial' font-size='9' text-anchor='middle' fill='#000000'>%</text>\n" (fmt3 lx) (fmt3 ly) vd.name to:f
									)
									-- scale bar
									local niceL = 1.0
									for k = -6 to 6 do
										for b in #(1.0, 2.0, 5.0) do
										(
											local L = b * (10.0 ^ k)
											if (L * sc) >= 40.0 and (L * sc) <= 160.0 do niceL = L
										)
									local barPx = niceL * sc
									if barPx <= (pageW - 2 * m) do
									(
										local bx = pageW - m - barPx
										local by = pageH - 10.0
										format "<g id='scale_bar' stroke='#000000' stroke-width='0.5'>\n" to:f
										format "<line x1='%' y1='%' x2='%' y2='%'/>\n" (fmt3 bx) (fmt3 by) (fmt3 (bx + barPx)) (fmt3 by) to:f
										format "<line x1='%' y1='%' x2='%' y2='%'/>\n" (fmt3 bx) (fmt3 (by - 3.0)) (fmt3 bx) (fmt3 (by + 3.0)) to:f
										format "<line x1='%' y1='%' x2='%' y2='%'/>\n" (fmt3 (bx + barPx)) (fmt3 (by - 3.0)) (fmt3 (bx + barPx)) (fmt3 (by + 3.0)) to:f
										format "</g>\n" to:f
										format "<text x='%' y='%' font-family='Arial' font-size='8' text-anchor='middle' fill='#000000'>% units</text>\n" (fmt3 (bx + barPx / 2.0)) (fmt3 (by - 5.0)) (niceL as string) to:f
									)
									format "</svg>\n" to:f
									close f

									local dt = (timestamp() - t0) / 1000.0
									local msg = "Exported in " + (dt as string) + " s\n\n" + filePath
									if failObjs.count > 0 do msg = msg + "\n\nSkipped objects: " + (failObjs as string)
									msg = msg + "\n\nOpen the SVG in Adobe Illustrator:\neach view is a named group of editable paths\n(Object > Release to Layers turns groups into layers)."
									messageBox msg
								)
								catch
								(
									try ( close f ) catch ( false )
									messageBox ("Error while writing SVG:\n" + (getCurrentException() as string))
								)
							)
						)
					)
					pbMain.value = 0
				)
			)
		)
	)

	on execute do
	(
		try ( destroyDialog roLV ) catch ( false )
		createDialog roLV
	)
)

-- Auto-open the dialog when this file is dragged into 3ds Max.
-- Remove the line below if you copy this file into a startup scripts folder.
try ( macros.run "LineView" "LineViewToSVG" ) catch ( format "Macro LineView/LineViewToSVG defined.\n" )
