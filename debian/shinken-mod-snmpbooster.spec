Name:		shinken-mod-snmpbooster
Version:	2.0~alpha
Release:	1
Summary:	Shinken Module SNMP for Poller

Group:		Network
License:	AGPLv3+
URL:		https://github.com/savoirfairelinux/mod-booster-snmp
Source0:	%{name}_%{version}.orig.tar.gz

BuildArch:  noarch

Requires:	shinken-common >= 2.0
BuildRequires:  python-setuptools

%description
Flexible monitoring tool - SNMP module for Poller
SNMP module for Arbiter/Scheduler/Poller. This module makes SNMP requests
without any SNMP plugin.


%prep
%setup -q


%build


%install
rm -rf %{buildroot}/*

rm module/tools/dump_redis.py
install -d %{buildroot}/usr/share/pyshared/shinken/modules/

%{__python} setup.py install -O1 --skip-build --root %{buildroot} --install-lib=%{python_sitelib}

ln -s %{python_sitelib}/mod-snmpbooster  %{buildroot}/usr/share/pyshared/shinken/modules/snmp_booster

install -d %{buildroot}/usr/share/doc/%{name}
cp -r doc/* %{buildroot}/%{_docdir}/%{name}

install -d %{buildroot}/etc/shinken/modules
install -pm0755 etc/modules/* %{buildroot}/etc/shinken/modules


%files
/usr/share/pyshared/shinken/modules/snmp_booster
%{python_sitelib}/mod_snmpbooster-*.egg-info
%config(noreplace) %{_sysconfdir}/shinken/modules/
%{_bindir}/sbcm
%doc %{_docdir}/%{name}/*


%changelog
* Wed May 27 2015 Sebastien Coavoux <sebastien.coavoux@savoirfairelinux.com> 2.0~alpha-1
- New upstream version

* Wed Apr 22 2015 Sebastien Coavoux <sebastien.coavoux@savoirfairelinux.com> 1.99.13-2
- Update package and doc

* Fri Apr 17 2015 Sebastien Coavoux <sebastien.coavoux@savoirfairelinux.com> 1.99.13-1
- Beta 13 of the new SNMPBooster

* Thu Mar 05 2015 Thibault Cohen <thibaut.cohen@savoirfairelinux.com>  1.99.12-2
- Initial Package
