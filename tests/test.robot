*** Settings ***
Resource   resource.robot
Variables  vars.robot
Library    robot_lib.py

*** Test Cases ***
Test
    Log  1
	My Internal Keyword
	#  in line comment
	My External Keyword  ${arg1}  ${arg2}=3
	

Test
    Log  2
	
Test With Invalid Char.
    Log  1

*** Keywords ***
My Internal Keyword
    [Documentation]  This is doc
    Log  My Interal Keyword  # extra comment ${arg}
	
Missing Keyword Documentation
    Log  1
	
Missing Doc But Disabled Rule  # roblint: disable=missing-doc-keyword
    Log  2
	
Keyword With Invalid Char?
    Log  1