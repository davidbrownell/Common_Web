@REM ----------------------------------------------------------------------
@REM |
@REM |  RelationalDataToSwaggerExample.cmd
@REM |
@REM |  David Brownell <db@DavidBrownell.com>
@REM |      2021-06-07 07:03:02
@REM |
@REM ----------------------------------------------------------------------
@REM |
@REM |  Copyright David Brownell 2021-22
@REM |  Distributed under the Boost Software License, Version 1.0. See
@REM |  accompanying file LICENSE_1_0.txt or copy at
@REM |  http://www.boost.org/LICENSE_1_0.txt.
@REM |
@REM ----------------------------------------------------------------------
@REM Converts from SimpleSchemaGenerator relational data to a Swagger/OpenAPI
@REM specification using SimpleSchemaGenerator and HttpGenerator. This file is
@REM for demonstration purposes only.

@echo off

set _output_dir=%~dp0Generated

echo ----------------------------------------------------------------------
echo ^|
echo ^|  Generating REST Content
echo ^|
echo ----------------------------------------------------------------------
call SimpleSchemaGenerator ^
    Generate ^
    HttpGeneratorRest ^
    RestContent ^
    "%_output_dir%\RestContent" ^
    "/input=%DEVELOPMENT_ENVIRONMENT_SIMPLE_SCHEMA_ROOT_DIR%\Libraries\Python\CommonSimpleSchemaGenerator\v1.0\CommonSimpleSchemaGenerator\RelationalPluginImpl.TestData.SimpleSchema" ^
    /verbose

if %ERRORLEVEL% NEQ 0 (exit /B %ERRORLEVEL%)

echo ----------------------------------------------------------------------
echo ^|
echo ^|  Generating JSONApi Content
echo ^|
echo ----------------------------------------------------------------------
python ^
    "%~dp0\..\..\src\HttpGenerator" ^
    Generate ^
    JsonApiRest ^
    "%_output_dir%\JsonApiContent" ^
    "/input=%_output_dir%\RestContent\RestContent.yaml" ^
    /verbose

if %ERRORLEVEL% NEQ 0 (exit /B %ERRORLEVEL%)

echo ----------------------------------------------------------------------
echo ^|
echo ^|  Generating Swagger Content
echo ^|
echo ----------------------------------------------------------------------
python ^
    "%~dp0\..\..\src\HttpGenerator" ^
    Generate ^
    Swagger ^
    "%_output_dir%\SwaggerContent" ^
    "/input=%_output_dir%\JsonApiContent\RestContent.yaml" ^
    "/plugin_arg=title:Relational Plugin Test Data" ^
    "/plugin_arg=api_version:0.0.1" ^
    "/plugin_arg=server_uri:http\://does_not_exist.com" ^
    "/plugin_arg=license_name:No License" ^
    /verbose

if %ERRORLEVEL% NEQ 0 (exit /B %ERRORLEVEL%)

echo Swagger Content has been generated and is available at:
echo.
echo    %_output_dir%\SwaggerContent\Swagger.yaml
echo.
