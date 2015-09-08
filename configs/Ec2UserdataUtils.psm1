<#
This Source Code Form is subject to the terms of the Mozilla Public
License, v. 2.0. If a copy of the MPL was not distributed with this
file, You can obtain one at http://mozilla.org/MPL/2.0/.
.Synopsis
  Utility functions for bootstraping an AWS EC2 instance with cloud-tools (https://github.com/mozilla/build-cloud-tools)
#>
function Write-Log {
  <#
  .Synopsis
    Logs to the userdata run log file, with timestamps.
  .Parameter message
    The body of the log message
  .Parameter severity
    The severity of the message, to enable filtering in log aggregators or reporting.
  .Parameter path
    The full path to the log file.
  #>
  param (
    [string] $message,
    [string] $severity = 'INFO',
    [string] $path = ('{0}\log\userdata-run.log' -f $env:SystemDrive)
  )
  if (!(Test-Path $path)) {
    [Environment]::SetEnvironmentVariable('OutputToConsole', 'true', 'Process')
  }
  $formattedMessage = ('{0} [{1}] {2}' -f [DateTime]::Now.ToString("yyyy-MM-dd HH:mm:ss"), $severity, $message)
  Add-Content -Path $path -Value $formattedMessage
  if ($env:OutputToConsole -eq 'true') {
    switch ($severity) 
    {
      'DEBUG' { Write-Host -Object $formattedMessage -ForegroundColor 'DarkGray' }
      'ERROR' { Write-Host -Object $formattedMessage -ForegroundColor 'Red' }
      default { Write-Host -Object $formattedMessage }
    }
  }
}

function Send-Log {
  <#
  .Synopsis
    Mails the specified logfile to the configured recipient(s)
  .Parameter logfile
    The full path to the log file to be mailed.
  .Parameter subject
    The subject line of the message.
  .Parameter to
    The recipient(s) of the message.
  .Parameter from
    The sender of the message.
  .Parameter smtpServer
    The smtp server that relays log messages.
  #>
  param (
    [string] $logfile,
    [string] $subject,
    [string] $to,
    [string] $from = ('{0}@{1}.{2}' -f $env:USERNAME, $env:COMPUTERNAME, $env:USERDOMAIN),
    [string] $smtpServer = 'smtp.mail.scl3.mozilla.com'
  )
  Send-MailMessage -To $to -Subject $subject -Body ([IO.File]::ReadAllText($logfile)) -SmtpServer $smtpServer -From $from
}

function Enable-UserdataPersist {
  <#
  .Synopsis
    Sets Ec2ConfigService Ec2HandleUserData to enabled in config.
  .Description
    Modifies Ec2ConfigService config file and logs settings at time of check.
  .Parameter ec2SettingsFile
    The full path to the config file for Ec2ConfigService.
  #>
  param (
    [string] $ec2SettingsFile = "C:\Program Files\Amazon\Ec2ConfigService\Settings\Config.xml"
  )
  $modified = $false;
  [xml]$xml = (Get-Content $ec2SettingsFile)
  foreach ($plugin in $xml.DocumentElement.Plugins.Plugin) {
    Write-Log -message ('plugin state of {0} read as: {1}, in: {2}' -f $plugin.Name, $plugin.State, $ec2SettingsFile) -severity 'DEBUG'
    if ($plugin.Name -eq "Ec2HandleUserData") {
      if ($plugin.State -ne "Enabled") {
        Write-Log -message ('changing state of Ec2HandleUserData plugin from: {0} to: Enabled, in: {1}' -f $plugin.State, $ec2SettingsFile) -severity 'INFO'
        $plugin.State = "Enabled"
        $modified = $true;
      }
    }
  }
  if ($modified) {
    Write-Log -message ('granting full access to: System, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
    $icaclsArgs = @($ec2SettingsFile, '/grant', 'System:F')
    & 'icacls' $icaclsArgs
    $xml.Save($ec2SettingsFile)
  }
  Write-Log -message ('granting read access to: Everyone, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/grant', 'Everyone:R')
  & 'icacls' $icaclsArgs
  Write-Log -message ('removing all inherited permissions on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/inheritance:r')
  & 'icacls' $icaclsArgs
  Write-Log -message ('removing access for: root, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/remove:g', 'root')
  & 'icacls' $icaclsArgs
  Write-Log -message ('removing access for: Administrators, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/remove:g', 'Administrators')
  & 'icacls' $icaclsArgs
  Write-Log -message ('removing access for: Users, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/remove:g', 'Users')
  & 'icacls' $icaclsArgs
  Write-Log -message ('removing access for: System, on: {0}' -f $ec2SettingsFile) -severity 'DEBUG'
  $icaclsArgs = @($ec2SettingsFile, '/remove:g', 'System')
  & 'icacls' $icaclsArgs
}

function Stop-ComputerWithDelay {
  <#
  .Synopsis
    Shuts down the computer and optionally restarts, logging a reason to the event log.
  .Parameter reason
    The reason for the shutdown or reboot.
  .Parameter delayInSeconds
    The time delay in seconds before shutting down
  .Parameter restart
    Whether or not to restart after shutdown
  #>
  param (
    [string] $reason,
    [int] $delayInSeconds = 10,
    [switch] $restart
  )
  Write-Log -message ('shutting down with reason: {0}' -f $reason) -severity 'INFO'
  if ($restart) {
    $stopArgs = @('-r', '-t', $delayInSeconds, '-c', $reason, '-f', '-d', 'p:4:1')
  } else {
    $stopArgs = @('-s', '-t', $delayInSeconds, '-c', $reason, '-f', '-d', 'p:4:1')
  }
  & 'shutdown' $stopArgs
}

function Does-FileContain {
  <#
  .Synopsis
    Determine if a file contains the specified string
  .Parameter needle
    The string to search for.
  .Parameter haystack
    The full path to the file to be checked.
  #>
  param (
    [string] $haystack,
    [string] $needle
  )
  if (((Get-Content $haystack) | % { $_ -Match "$needle" }) -Contains $true) {
    return $true
  } else {
    return $false
  }
}

function Has-PuppetRunSuccessfully {
  <#
  .Synopsis
    Determine if a successful puppet run has completed
  .Parameter puppetLog
    The full path to the puppet log file.
  #>
  param (
    [string] $puppetLog
  )
  if ((Test-Path $puppetLog) -and (Does-FileContain -haystack $puppetLog -needle "Puppet \(notice\): Finished catalog run")) {
    return $true
  } else {
    return $false
  }
}

function Disable-Service {
  <#
  .Synopsis
    Stops and disables a windows service
  .Parameter serviceName
    the name of the service to be disabled
  #>
  param (
    [string] $serviceName
  )
  Write-Log -message ('stopping and disabling service: {0}' -f $serviceName) -severity 'INFO'
  Get-Service $serviceName | Stop-Service -PassThru | Set-Service -StartupType disabled
}

function Disable-WindowsUpdate {
  <#
  .Synopsis
    Stops and disables the windows update service 
  #>
  $autoUpdateSettings = (New-Object -com "Microsoft.Update.AutoUpdate").Settings
  if ($autoUpdateSettings.NotificationLevel -ne 1) {
    Write-Log -message 'disabling Windows Update notifications' -severity 'INFO'
    $autoUpdateSettings.NotificationLevel=1
    $autoUpdateSettings.Save()
  } else {
    Write-Log -message 'detected disabled Windows Update notifications' -severity 'DEBUG'
  }
  Disable-Service -serviceName 'wuauserv'
}

function Disable-PuppetService {
  <#
  .Synopsis
    Stops and disables the puppet service and deletes the RunPuppet scheduled task
  #>
  Disable-Service -serviceName 'puppet'
  Write-Log -message 'deleting RunPuppet scheduled task' -severity 'INFO'
  $schtasksArgs = @('/delete', '/tn', 'RunPuppet', '/f')
  & 'schtasks' $schtasksArgs
}

function Run-Puppet {
  <#
  .Synopsis
    Runs the puppet agent
  .Description
    Runs the puppetization vbscript
    Runs the puppet agent in cli mode, logging to an output file
    Deletes the RunPuppet scheduled task
  .Parameter hostname
    The hostname of the instance, required for facter env vars.
  .Parameter domain
    The domain of the instance, required for facter env vars.
  #>
  param (
    [string] $hostname,
    [string] $domain,
    [string] $puppetServer = 'puppet',
    [string] $logdest
  )
  Write-Log -message 'setting environment variables' -severity 'INFO'
  [Environment]::SetEnvironmentVariable("FACTER_domain", "$domain", "Process")
  [Environment]::SetEnvironmentVariable("FACTER_hostname", "$hostname", "Process")
  [Environment]::SetEnvironmentVariable("FACTER_fqdn", ("$hostname.$domain"), "Process")
  [Environment]::SetEnvironmentVariable("COMPUTERNAME", "$hostname", "Machine")
  [Environment]::SetEnvironmentVariable("USERDOMAIN", "$domain", "Machine")

  Write-Log -message 'running puppetization script' -severity 'INFO'
  #todo: log and mail output from vbs script
  cscript.exe ('{0}\Puppetlabs\puppet\var\puppettize_TEMP.vbs' -f $env:ProgramData)
  
  Write-Log -message ('running puppet agent, logging to: {0}' -f $logdest) -severity 'INFO'
  $puppetArgs = @('agent', '--test', '--detailed-exitcodes', '--server', $puppetServer, '--logdest', $logdest)
  & 'puppet' $puppetArgs

  Write-Log -message 'deleting RunPuppet scheduled task (again)' -severity 'INFO'
  $schtasksArgs = @('/delete', '/tn', 'RunPuppet', '/f')
  & 'schtasks' $schtasksArgs
}

function Is-HostnameSetCorrectly {
  <#
  .Synopsis
    Determines if the hostname is correctly set
  .Parameter hostnameExpected
    The expected hostname of the instance.
  #>
  param (
    [string] $hostnameExpected
  )
  $hostnameActual = [System.Net.Dns]::GetHostName()
  if ("$hostnameExpected" -ieq "$hostnameActual") {
    return $true
  } else {
    Write-Log -message ('net dns hostname: {0}, expected: {1}' -f $hostnameActual, $hostnameExpected) -severity 'DEBUG'
    Write-Log -message ('computer name env var: {0}, expected: {1}' -f $env:COMPUTERNAME, $hostnameExpected) -severity 'DEBUG'
    return $false
  }
}

function Set-Hostname {
  <#
  .Synopsis
    Sets the hostname
  .Description
    - Sets the COMPUTERNAME environment variable at the machine level
    - Renames the computer
    - Adds the new hostname to the sysprep file, to prevent sysprep from reverting the hostname on reboot
  .Parameter hostname
    The required new hostname of the instance.
  #>
  param (
    [string] $hostname
  )
  [Environment]::SetEnvironmentVariable("COMPUTERNAME", "$hostname", "Machine")
  (Get-WmiObject Win32_ComputerSystem).Rename("$hostname")
  Write-Log -message ('hostname set to: {0}' -f $hostname) -severity 'INFO'
  $sysprepFile = ('{0}\Amazon\Ec2ConfigService\sysprep2008.xml' -f $env:ProgramFiles)
  [xml] $xml = Get-Content($sysprepFile)
  foreach ($settings in $xml.DocumentElement.settings) {
    if ($settings.pass -eq "specialize") {
      foreach ($component in $settings.component) {
        if ($component.name -eq "Microsoft-Windows-Shell-Setup") {
          if (-not $component.ComputerName) {
            $computerNameElement = $xml.CreateElement("ComputerName")
            $computerNameElement.AppendChild($xml.CreateTextNode("$hostname"))
            $component.AppendChild($computerNameElement)
            Write-Log -message ('computer name inserted to: {0}' -f $sysprepFile) -severity 'DEBUG'
          } else {
            $component.ComputerName.value = "$hostname"
            Write-Log -message ('computer name updated in: {0}' -f $sysprepFile) -severity 'DEBUG'
          }
        }
      }
    }
  }
  $xml.Save($sysprepFile)
}

function Is-DomainSetCorrectly {
  <#
  .Synopsis
    Determines if the primary dns suffix is correctly set
  .Parameter domainExpected
    The expected primary dns suffix of the instance.
  #>
  param (
    [string] $domainExpected
  )
  $primaryDnsSuffix = (Get-ItemProperty "HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\" -Name "NV Domain")."NV Domain"
  if ("$domainExpected" -ieq "$primaryDnsSuffix") {
    return $true
  } else {
    Write-Log -message ('nv domain registry key: {0}, expected: {1}' -f $primaryDnsSuffix, $domainExpected) -severity 'DEBUG'
    return $false
  }
}

function Set-Domain {
  <#
  .Synopsis
    Set the primary DNS suffix (for FQDN)
  .Parameter domain
    The required new primary DNS suffix of the instance.
  #>
  param (
    [string] $domain
  )
  [Environment]::SetEnvironmentVariable("USERDOMAIN", "$domain", "Machine")
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\' -Name 'Domain' -Value "$domain"
  Set-ItemProperty 'HKLM:\SYSTEM\CurrentControlSet\Services\Tcpip\Parameters\' -Name 'NV Domain' -Value "$domain"
  Write-Log -message ('Primary DNS suffix set to: {0}' -f $domain) -severity 'INFO'
}

# determines if the log aggregator is correctly set
function Is-AggregatorConfiguredCorrectly {
  <#
  .Synopsis
    Determines if the log aggregator is correctly set
  .Parameter aggregator
    The fqdn of the log aggregator for the current aws region.
  #>
  param (
    [string] $aggregator
  )
  $conf = ('{0}\nxlog\conf\nxlog_target_aggregator.conf' -f ${env:ProgramFiles(x86)})
  if ((Test-Path $conf) -and (Does-FileContain -haystack $conf -needle $aggregator)) {
    return $true
  } else {
    return $false
  }
}

function Set-Aggregator {
  <#
  .Synopsis
    Sets the fqdn of the log aggregator for the current aws region.
  .Description
    Modifies the nxlog configuration file to point to the specified log aggregator and restarts the nxlog service.
  .Parameter aggregator
    The fqdn of the log aggregator for the current aws region.
  #>
  param (
    [string] $aggregator
  )
  $conf = ('{0}\nxlog\conf\nxlog_target_aggregator.conf' -f ${env:ProgramFiles(x86)})
  if (Test-Path $conf) {
    (Get-Content $conf) | 
      Foreach-Object { $_ -replace "(Host [^ ]*)", "Host $aggregator" } | 
        Set-Content $conf
    Restart-Service nxlog
    Write-Log -message "log aggregator set to: $aggregator" -severity 'INFO'
  }
}

function Disable-Firewall {
  <#
  .Synopsis
    Disables the Windows Firewall for the specified profile.
  .Parameter profile
    The profile to disable the firewall under. Defaults to CurrentProfile.
  #>
  param (
    [string] $profile = 'AllProfiles'
  )
  Write-Log -message 'disabling Windows Firewall' -severity 'INFO'
  $netshArgs = @('advfirewall', 'set', $profile, 'state', 'off')
  & 'netsh' $netshArgs
  #Set-ItemProperty -path HKLM:\Software\Policies\Microsoft\WindowsFirewall\DomainProfile -name EnableFirewall -value 0
  #Set-ItemProperty -path HKLM:\Software\Policies\Microsoft\WindowsFirewall\PrivateProfile -name EnableFirewall -value 0
  #Set-ItemProperty -path HKLM:\Software\Policies\Microsoft\WindowsFirewall\PublicProfile -name EnableFirewall -value 0
  # setting the keys above has no effect due to a group policy setting. removing the section, has the desired effect.
  Remove-Item -path HKLM:\Software\Policies\Microsoft\WindowsFirewall -recurse -force
}