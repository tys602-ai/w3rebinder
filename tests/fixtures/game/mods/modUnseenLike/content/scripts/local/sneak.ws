down = theInput.IsActionPressed( 'XXSneak' ) || theInput.IsActionPressed( 'DiveDown' ) || ComboHeld();
return theInput.IsActionPressed( 'XXSneakCombo' ) && theInput.IsActionPressed( 'XXSneakMod' );
if ( theInput.IsActionPressed( 'Sprint' ) && !theInput.IsActionPressed( 'XXSneak' ) ) {}
v = theInput.GetActionValue( 'GI_AxisLeftY' );
