# -*- coding: utf-8 -*-
#!/usr/bin/python2.7

#description     :This file creates a map: Calculates all intersecting polygons with a "landuse"-tag
#author          :Christopher Barron  @ http://giscience.uni-hd.de/
#date            :19.01.2013
#version         :0.1
#usage           :python pyscript.py
#==============================================================================

import psycopg2
import mapnik2
from optparse import OptionParser
import sys, os, subprocess
import cStringIO
import mapnik2

# import db connection parameters
import db_conn_para as db

###
###
db_name = db.g_my_dbname
db_user = db.g_my_username
hostname = db.g_my_hostname
db_pw = db.g_my_dbpassword
###
### 

###
### Path to OSM-XML file (should be provided in the "osm-mapnik-style"-folder providedby Mapnik
path_to_osm_xml = "/opt/osm-mapnik-style/osm.xml"
###
###

###
### Path to Point-Symbolizer for point objects that are overlai
point_marker = '../iOSMAnalyzer/pin.png'

###
### Width (in px), Height (in px), Name and Format of the output-picture
pic_output_width = 1200
pic_output_height = 800
pic_output_name = 'pics/c6_map_natural_intersect'
pic_output_format = 'jpeg'
###
###

###
### database-query for overlay-data
db_query = '''(

-- Select only the intersecting areas within all currently valid landuse-polygons. Filter by 10% of their original size so only overlapping fragments of landuse-polygons which aren't digitalized correctly are shown.
-- This is neccessary as not every polygon tagged with landuse shouldn't overlapp. (e.g. landuse=military and landuse=forest).
SELECT 
	geom_intersect AS geom,
	area
FROM
	(SELECT 
		geom_intersect, 
		(ST_Area(
			ST_GeographyFromText(
				ST_AsText(
					ST_Transform(geom_intersect,4326)
				)
			)
		)) AS area,
		foo.geom1 AS geom1,
		foo.geom2 AS geom2 
	FROM -- area in m² 
		(SELECT 
			ST_Intersection(part_1.geom, part_2.geom) AS geom_intersect, 
			part_1.geom AS geom1, 
			part_2.geom AS geom2
		FROM  
			-- valid landuse polygons: Part 1
			(SELECT * 
			FROM 
				hist_polygon 
			WHERE 
				tags ? 'landuse' AND ST_IsValid(geom) AND visible = 'true' AND
				(version = (SELECT max(version) FROM hist_polygon AS h WHERE h.id = hist_polygon.id AND
					(valid_from <= CURRENT_TIMESTAMP AND (valid_to >= CURRENT_TIMESTAMP OR valid_to is null))) 
				AND minor = (SELECT max(minor) FROM hist_polygon AS h WHERE h.id = hist_polygon.id AND h.version = hist_polygon.version AND
					(valid_from <= CURRENT_TIMESTAMP AND (valid_to >= CURRENT_TIMESTAMP OR valid_to is null))))
			) AS part_1,

			-- valid landuse polygons: Part 2
			(SELECT * 
			FROM 
				hist_polygon 
			WHERE 
				tags ? 'landuse' AND ST_IsValid(geom) AND visible = 'true' AND
				(version = (SELECT max(version) FROM hist_polygon AS h WHERE h.id = hist_polygon.id AND
					(valid_from <= CURRENT_TIMESTAMP AND (valid_to >= CURRENT_TIMESTAMP OR valid_to is null))) 
				AND minor = (SELECT max(minor) FROM hist_polygon AS h WHERE h.id = hist_polygon.id AND h.version = hist_polygon.version AND
					(valid_from <= CURRENT_TIMESTAMP AND (valid_to >= CURRENT_TIMESTAMP OR valid_to is null))))
			) AS part_2
		WHERE 
			part_1.id <> part_2.id AND 
			ST_Intersects(part_1.geom, part_2.geom)
		) AS foo
	ORDER BY area) AS foo2
WHERE
	area > 0
	
	AND
	
	(((ST_Area(
		ST_GeographyFromText(
			ST_AsText(
				ST_Transform(geom_intersect,4326)
			)
		)
	)) 
	*100 /
	(ST_Area(
		ST_GeographyFromText(
			ST_AsText(
				ST_Transform(foo2.geom1,4326)
			)
		)
	))) <=10)

	AND

	(((ST_Area(
		ST_GeographyFromText(
			ST_AsText(
				ST_Transform(geom_intersect,4326)
			)
		)
	)) 
	*100 /
	(ST_Area(
		ST_GeographyFromText(
			ST_AsText(
				ST_Transform(foo2.geom2,4326)
			)
		)
	))) <=10)
	
) AS foo'''
###
###


###
### Create views
dsn = ""
dbprefix = "hist"
viewprefix = "hist_view"
hstore = ""
date = 'CURRENT_TIMESTAMP'
viewcolumns = "access,addr:housename,addr:housenumber,addr:interpolation,admin_level,aerialway,aeroway,amenity,area,barrier,bicycle,brand,bridge,boundary,building,construction,covered,culvert,cutting,denomination,disused,embankment,foot,generator:source,harbour,highway,tracktype,capital,ele,historic,horse,intermittent,junction,landuse,layer,leisure,lock,man_made,military,motorcar,name,natural,oneway,operator,population,power,power_source,place,railway,ref,religion,route,service,shop,sport,surface,toll,tourism,tower:type,tunnel,water,waterway,wetland,width,wood"
extracolumns = ""
###
###

# Split columns into the osm2pgsql-database-schema for rendering with Mapnik
# This part of the code is taken from Peter Koerner's "OSM-History-Renderer" (https://github.com/MaZderMind/osm-history-renderer/blob/master/renderer/render.py)
columns = viewcolumns.split(',')
if(extracolumns):
    columns += options.extracolumns.split(',')

def create_views(dsn, dbprefix, viewprefix, hstore, columns, date):
    try:
      conn_string="dbname=%s user=%s host=%s password=%s" % (db_name, db_user, hostname, db_pw)
      print "Connecting to database\n->%s" % (conn_string)
      con = psycopg2.connect(conn_string)
      print "Connection to database was established succesfully"
    except:
      print "Connection to database failed"
    cur = con.cursor()
    
    columselect = ""
    for column in columns:
        columselect += "tags->'%s' AS \"%s\", " % (column, column)
    
    cur.execute("DELETE FROM geometry_columns WHERE f_table_catalog = '' AND f_table_schema = 'public' AND f_table_name IN ('%s_point', '%s_line', '%s_roads', '%s_polygon');" % (viewprefix, viewprefix, viewprefix, viewprefix))
    
    cur.execute("DROP VIEW IF EXISTS %s_point" % (viewprefix))
    cur.execute("CREATE OR REPLACE VIEW %s_point AS SELECT id AS osm_id, %s geom AS way FROM %s_point WHERE %s BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31');" % (viewprefix, columselect, dbprefix, date))
    cur.execute("INSERT INTO geometry_columns (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type) VALUES ('', 'public', '%s_point', 'way', 2, 900913, 'POINT');" % (viewprefix))
    
    cur.execute("DROP VIEW IF EXISTS %s_line" % (viewprefix))
    cur.execute("CREATE OR REPLACE VIEW %s_line AS SELECT id AS osm_id, %s z_order, geom AS way FROM %s_line WHERE %s BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31');" % (viewprefix, columselect, dbprefix, date))
    cur.execute("INSERT INTO geometry_columns (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type) VALUES ('', 'public', '%s_line', 'way', 2, 900913, 'LINESTRING');" % (viewprefix))
    
    cur.execute("DROP VIEW IF EXISTS %s_roads" % (viewprefix))
    cur.execute("CREATE OR REPLACE VIEW %s_roads AS SELECT id AS osm_id, %s z_order, geom AS way FROM %s_line WHERE %s BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31');" % (viewprefix, columselect, dbprefix, date))
    cur.execute("INSERT INTO geometry_columns (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type) VALUES ('', 'public', '%s_roads', 'way', 2, 900913, 'LINESTRING');" % (viewprefix))
    
    cur.execute("DROP VIEW IF EXISTS %s_polygon" % (viewprefix))
    cur.execute("CREATE OR REPLACE VIEW %s_polygon AS SELECT id AS osm_id, %s z_order, area AS way_area, geom AS way FROM %s_polygon WHERE %s BETWEEN valid_from AND COALESCE(valid_to, '9999-12-31');" % (viewprefix, columselect, dbprefix, date))
    cur.execute("INSERT INTO geometry_columns (f_table_catalog, f_table_schema, f_table_name, f_geometry_column, coord_dimension, srid, type) VALUES ('', 'public', '%s_polygon', 'way', 2, 900913, 'POLYGON');" % (viewprefix))
    
    # bbox-extent of database. Global variable for bbox extent
    cur.execute("SELECT ST_XMin(ST_Extent(ST_Transform(geom, 4326))) FROM %s_point;" % (dbprefix))
    global xmin
    xmin = cur.fetchone()[0]
        
    cur.execute("SELECT ST_YMin(ST_Extent(ST_Transform(geom, 4326))) FROM %s_point;" % (dbprefix))
    global ymin
    ymin = cur.fetchone()[0]
    
    cur.execute("SELECT ST_XMax(ST_Extent(ST_Transform(geom, 4326))) FROM %s_point;" % (dbprefix))
    global xmax
    xmax = cur.fetchone()[0]
    
    cur.execute("SELECT ST_YMax(ST_Extent(ST_Transform(geom, 4326))) FROM %s_point;" % (dbprefix))
    global ymax
    ymax = cur.fetchone()[0]
    con.commit()
    cur.close()
    con.close()


# Call function to create the views
create_views(dsn, dbprefix, viewprefix, hstore, columns, date)

# Create map with width height
m = mapnik2.Map(pic_output_width, pic_output_height)

# Load osm-xml-stylesheet for rendering the views
mapnik2.load_map(m, path_to_osm_xml)

# Define projection
prj = mapnik2.Projection("+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +no_defs +over")

# Map bounds. Bound values come from SQL-query
if hasattr(mapnik2, 'Box2d'):
    bbox = mapnik2.Box2d(xmin,ymin,xmax,ymax)
else:
    bbox = mapnik2.Envelope(xmin,ymin,xmax,ymax)

# Project bounds to map projection
e = mapnik2.forward_(bbox, prj)

# Zoom map to bounding box
m.zoom_to_box(e)



###
### START Layer 1
###

# style object to hold rules
s = mapnik2.Style() 

# rule object to hold symbolizers
r = mapnik2.Rule() 
r2 = mapnik2.Rule() 

# Lines (outlines of polygons and/or simple lines. Line-Color (RGB) line-thickness
polygon_symbolizer = mapnik2.PolygonSymbolizer(mapnik2.Color('red')) #rgb(5%,5%,5%)

# Point Style. Path to marker.png
point_symbolizer = mapnik2.PointSymbolizer(mapnik2.PathExpression(point_marker) )

# Allow Overlaps and set opacity of marker
point_symbolizer.allow_overlap = True
point_symbolizer.opacity = 0.7


# add the polygon_symbolizer to the rule object
r.symbols.append(polygon_symbolizer) 
r2.symbols.append(point_symbolizer) 



# now add the rule(s) to the style
s.rules.append(r) 
s.rules.append(r2)

# Styles are added to the map
m.append_style('My Style',s) 

# Projection from PostGIS-Layer-Data
lyr = mapnik2.Layer('Geometry from PostGIS', '+proj=merc +a=6378137 +b=6378137 +lat_ts=0.0 +lon_0=0.0 +x_0=0.0 +y_0=0 +k=1.0 +units=m +nadgrids=@null +no_defs +over')

# PostGIS-Connection + DB-Query
lyr.datasource = mapnik2.PostGIS(host=hostname, user=db_user, password=db_pw, dbname=db_name,table=db_query) 

# Append Style to layer
lyr.styles.append('My Style')

###
### END Layer 1
###

# Append overlay-layers to the map
m.layers.append(lyr)

###
### START scale
###

# center of the image
label_x = xmin + ((xmax - xmin) / 2)

# bottom of the image
label_y = ymin + ((ymax - ymin) / 30)

# create PointDatasource
pds = mapnik2.PointDatasource()

# place scale at the bottom-center of the map
pds.add_point(label_x, label_y, 'Name', "Scale: 1:" + str(m.scale_denominator()))

# create label symbolizers
if mapnik2.mapnik_version() >= 800:
    text = mapnik2.TextSymbolizer(mapnik2.Expression('[Name]'),'DejaVu Sans Bold',12,mapnik2.Color('black'))
else:
    text = mapnik2.TextSymbolizer('Name','DejaVu Sans Bold',12,mapnik2.Color('black'))

s3 = mapnik2.Style()
r3 = mapnik2.Rule()
r3.symbols.append(text)
s3.rules.append(r3)

lyr3 = mapnik2.Layer('Memory Datasource')
lyr3.datasource = pds
lyr3.styles.append('Style')
m.layers.append(lyr3)
m.append_style('Style',s3)

###
### END scale
###

# Render Mapnik-map to png-file
mapnik2.render_to_file(m, pic_output_name, pic_output_format)

del m
