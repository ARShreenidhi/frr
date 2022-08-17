#!/usr/bin/env python
#
# Copyright (c) 2022 by VMware, Inc. ("VMware")
# Used Copyright (c) 2018 by Network Device Education Foundation, Inc. ("NetDEF")
# in this file.
#
# Permission to use, copy, modify, and/or distribute this software
# for any purpose with or without fee is hereby granted, provided
# that the above copyright notice and this permission notice appear
# in all copies.
# Shreenidhi A R <rshreenidhi@vmware.com>
# THE SOFTWARE IS PROVIDED "AS IS" AND VMWARE DISCLAIMS ALL WARRANTIES
# WITH REGARD TO THIS SOFTWARE INCLUDING ALL IMPLIED WARRANTIES OF
# MERCHANTABILITY AND FITNESS. IN NO EVENT SHALL VMWARE BE LIABLE FOR
# ANY SPECIAL, DIRECT, INDIRECT, OR CONSEQUENTIAL DAMAGES OR ANY
# DAMAGES WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS,
# WHETHER IN AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS
# ACTION, ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE
# OF THIS SOFTWARE.
#
"""
Following tests are covered.
1. Verify the default route with 8 way ecmp topology
    R1===== (8links) ======R2

"""
import os
import sys
import time
import pytest
from copy import deepcopy
from lib.topolog import logger

# pylint: disable=C0413
# Import topogen and topotest helpers
from lib.topogen import Topogen, get_topogen
from lib.topojson import build_config_from_json
from lib.topolog import logger

from lib.bgp import (
    verify_bgp_convergence,
    create_router_bgp,
    get_dut_as_number,
    verify_rib_default_route,
    get_best_path_route_in_FIB,
)
from lib.common_config import (
    shutdown_bringup_interface,
    step,
    required_linux_kernel_version,
    create_route_maps,
    apply_raw_config,
    create_prefix_lists,
    get_frr_ipv6_linklocal,
    start_topology,
    write_test_header,
    check_address_types,
    write_test_footer,
    reset_config_on_routers,
    check_router_status,
)

# Save the Current Working Directory to find configuration files.
CWD = os.path.dirname(os.path.realpath(__file__))
sys.path.append(os.path.join(CWD, "../"))
sys.path.append(os.path.join(CWD, "../lib/"))

# Required to instantiate the topology builder class.
# pylint: disable=C0413
# Import topogen and topotest helpers

# Global variables
topo = None

pytestmark = [pytest.mark.bgpd, pytest.mark.staticd]


def setup_module(mod):
    """
    Sets up the pytest environment

    * `mod`: module name
    """

    # Required linux kernel version for this suite to run.
    result = required_linux_kernel_version("4.15")
    if result is not True:
        pytest.skip("Kernel requirements are not met")

    testsuite_run_time = time.asctime(time.localtime(time.time()))
    logger.info("Testsuite start time: {}".format(testsuite_run_time))
    logger.info("=" * 40)

    logger.info("Running setup_module to create topology")

    # This function initiates the topology build with Topogen...
    json_file = "{}/default_orginate_8_way_ecmp.json".format(CWD)
    tgen = Topogen(json_file, mod.__name__)
    global topo
    topo = tgen.json_topo
    # ... and here it calls Mininet initialization functions.

    # Starting topology, create tmp files which are loaded to routers
    #  to start daemons and then start routers
    start_topology(tgen)

    # Creating configuration from JSON
    build_config_from_json(tgen, topo)
    global BGP_CONVERGENCE
    global ADDR_TYPES

    ADDR_TYPES = check_address_types()
    BGP_CONVERGENCE = verify_bgp_convergence(tgen, topo)
    assert BGP_CONVERGENCE is True, "setup_module :Failed \n Error: {}".format(
        BGP_CONVERGENCE
    )

    logger.info("Running setup_module() done")


def teardown_module():
    """Teardown the pytest environment"""

    logger.info("Running teardown_module to delete topology")

    tgen = get_topogen()

    # Stop toplogy and Remove tmp files
    tgen.stop_topology()

    logger.info(
        "Testsuite end time: {}".format(time.asctime(time.localtime(time.time())))
    )
    logger.info("=" * 40)


#####################################################
#
#                      Testcases
#
#####################################################
def test_verify_default_originate_with_8way_ecmp_p2(request):
    """
    Summary: "Verify default-originate route with 8 way ECMP and traffic "
    """

    tgen = get_topogen()
    global BGP_CONVERGENCE
    global DEFAULT_ROUTES
    DEFAULT_ROUTES = {"ipv4": "0.0.0.0/0", "ipv6": "0::0/0"}

    if BGP_CONVERGENCE != True:
        pytest.skip("skipped because of BGP Convergence failure")
    # test case name
    tc_name = request.node.name
    write_test_header(tc_name)
    if tgen.routers_have_failure():
        check_router_status(tgen)
    reset_config_on_routers(tgen)

    step("Populating next-hops details")
    r1_r2_ipv4_neighbor_ips = []
    r1_r2_ipv6_neighbor_ips = []
    r1_link = None
    for index in range(1, 9):
        r1_link = "r1-link" + str(index)
        r1_r2_ipv4_neighbor_ips.append(
            topo["routers"]["r2"]["links"][r1_link]["ipv4"].split("/")[0]
        )
        r1_r2_ipv6_neighbor_ips.append(
            topo["routers"]["r2"]["links"][r1_link]["ipv6"].split("/")[0]
        )

    step(
        "Configure default-originate on R1 for all the neighbor of IPv4 and IPv6 peers "
    )
    local_as = get_dut_as_number(tgen, dut="r1")
    for index in range(8):
        raw_config = {
            "r1": {
                "raw_config": [
                    "router bgp {}".format(local_as),
                    "address-family ipv4 unicast",
                    "neighbor {} default-originate".format(
                        r1_r2_ipv4_neighbor_ips[index]
                    ),
                    "exit-address-family",
                    "address-family ipv6 unicast",
                    "neighbor {} default-originate ".format(
                        r1_r2_ipv6_neighbor_ips[index]
                    ),
                    "exit-address-family",
                ]
            }
        }
        result = apply_raw_config(tgen, raw_config)
        assert result is True, "Testcase {} : Failed Error: {}".format(tc_name, result)

    step(
        "After configuring default-originate command , verify default  routes are advertised on R2 "
    )

    r2_link = None
    for index in range(1, 9):
        r2_link = "r2-link" + str(index)
        ipv4_nxt_hop = topo["routers"]["r1"]["links"][r2_link]["ipv4"].split("/")[0]
        interface = topo["routers"]["r1"]["links"][r2_link]["interface"]
        ipv6_link_local_nxt_hop = get_frr_ipv6_linklocal(tgen, "r1", intf=interface)
        DEFAULT_ROUTE_NXT_HOP = {"ipv4": ipv4_nxt_hop, "ipv6": ipv6_link_local_nxt_hop}

        result = verify_rib_default_route(
            tgen,
            topo,
            dut="r2",
            routes=DEFAULT_ROUTES,
            expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
        )
        assert result is True, "Testcase {} : Failed \n Error: {}".format(
            tc_name, result
        )

    step("Ping R1 configure IPv4 and IPv6 loopback address from R2")
    pingaddr = topo["routers"]["r1"]["links"]["lo"]["ipv4"].split("/")[0]
    router = tgen.gears["r2"]
    output = router.run("ping -c 4 -w 4 {}".format(pingaddr))
    assert " 0% packet loss" in output, "Ping R1->R2  FAILED"
    logger.info("Ping from R1 to R2 ... success")

    step("Shuting up the active route")
    network = {"ipv4": "0.0.0.0/0", "ipv6": "::/0"}
    ipv_dict = get_best_path_route_in_FIB(tgen, topo, dut="r2", network=network)
    dut_links = topo["routers"]["r1"]["links"]
    active_interface = None
    for key, values in dut_links.items():
        ipv4_address = dut_links[key]["ipv4"].split("/")[0]
        ipv6_address = dut_links[key]["ipv6"].split("/")[0]
        if ipv_dict["ipv4"] == ipv4_address and ipv_dict["ipv6"] == ipv6_address:
            active_interface = dut_links[key]["interface"]

    logger.info(
        "Shutting down the interface {} on router {} ".format(active_interface, "r1")
    )
    shutdown_bringup_interface(tgen, "r1", active_interface, False)

    step("Verify the complete convergence  to fail after  shutting  the interface")
    result = verify_bgp_convergence(tgen, topo, expected=False)
    assert (
        result is not True
    ), " Testcase {} : After shuting down the interface  Convergence is expected to be Failed".format(
        tc_name
    )

    step(
        "Verify  routes from active best path is not received from  r1 after  shuting the interface"
    )
    r2_link = None
    for index in range(1, 9):
        r2_link = "r2-link" + str(index)
        ipv4_nxt_hop = topo["routers"]["r1"]["links"][r2_link]["ipv4"].split("/")[0]
        interface = topo["routers"]["r1"]["links"][r2_link]["interface"]
        ipv6_link_local_nxt_hop = get_frr_ipv6_linklocal(tgen, "r1", intf=interface)
        DEFAULT_ROUTE_NXT_HOP = {"ipv4": ipv4_nxt_hop, "ipv6": ipv6_link_local_nxt_hop}
        if index == 1:
            result = verify_rib_default_route(
                tgen,
                topo,
                dut="r2",
                routes=DEFAULT_ROUTES,
                expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
                expected=False,
            )
            assert result is not True, "Testcase {} : Failed \n Error: {}".format(
                tc_name, result
            )
        else:
            result = verify_rib_default_route(
                tgen,
                topo,
                dut="r2",
                routes=DEFAULT_ROUTES,
                expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
            )
            assert result is True, "Testcase {} : Failed \n Error: {}".format(
                tc_name, result
            )

    step("Ping R1 configure IPv4 and IPv6 loopback address from R2")
    pingaddr = topo["routers"]["r1"]["links"]["lo"]["ipv4"].split("/")[0]
    router = tgen.gears["r2"]
    output = router.run("ping -c 4 -w 4 {}".format(pingaddr))
    assert " 0% packet loss" in output, "Ping R1->R2  FAILED"
    logger.info("Ping from R1 to R2 ... success")

    step("No Shuting up the active route")

    shutdown_bringup_interface(tgen, "r1", active_interface, True)

    step("Verify the complete convergence after bringup the interface")
    result = verify_bgp_convergence(tgen, topo)
    assert (
        result is True
    ), " Testcase {} : After bringing up  the interface  complete convergence is expected ".format(
        tc_name
    )

    step("Verify all the routes are received from  r1 after no shuting the interface")
    r2_link = None
    for index in range(1, 9):
        r2_link = "r2-link" + str(index)
        ipv4_nxt_hop = topo["routers"]["r1"]["links"][r2_link]["ipv4"].split("/")[0]
        interface = topo["routers"]["r1"]["links"][r2_link]["interface"]
        ipv6_link_local_nxt_hop = get_frr_ipv6_linklocal(tgen, "r1", intf=interface)
        DEFAULT_ROUTE_NXT_HOP = {"ipv4": ipv4_nxt_hop, "ipv6": ipv6_link_local_nxt_hop}
        if index == 1:
            result = verify_rib_default_route(
                tgen,
                topo,
                dut="r2",
                routes=DEFAULT_ROUTES,
                expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
            )
            assert result is True, "Testcase {} : Failed \n Error: {}".format(
                tc_name, result
            )
        else:
            result = verify_rib_default_route(
                tgen,
                topo,
                dut="r2",
                routes=DEFAULT_ROUTES,
                expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
            )
            assert result is True, "Testcase {} : Failed \n Error: {}".format(
                tc_name, result
            )

    step(
        "Configure IPv4 and IPv6  route-map with deny option on R2 to filter default route  0.0.0.0/0 and 0::0/0"
    )
    DEFAULT_ROUTES = {"ipv4": "0.0.0.0/0", "ipv6": "0::0/0"}
    input_dict_3 = {
        "r2": {
            "prefix_lists": {
                "ipv4": {
                    "Pv4": [
                        {
                            "seqid": "1",
                            "network": DEFAULT_ROUTES["ipv4"],
                            "action": "permit",
                        }
                    ]
                },
                "ipv6": {
                    "Pv6": [
                        {
                            "seqid": "1",
                            "network": DEFAULT_ROUTES["ipv6"],
                            "action": "permit",
                        }
                    ]
                },
            }
        }
    }
    result = create_prefix_lists(tgen, input_dict_3)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    input_dict_3 = {
        "r2": {
            "route_maps": {
                "RMv4": [
                    {
                        "action": "deny",
                        "seq_id": "1",
                        "match": {"ipv4": {"prefix_lists": "Pv4"}},
                    },
                ],
                "RMv6": [
                    {
                        "action": "deny",
                        "seq_id": "1",
                        "match": {"ipv6": {"prefix_lists": "Pv6"}},
                    },
                ],
            }
        }
    }
    result = create_route_maps(tgen, input_dict_3)
    assert result is True, "Testcase {} : Failed \n Error: {}".format(tc_name, result)

    step("Apply route-map IN direction of R2 ( R2-R1) for IPv4 and IPv6 BGP neighbors")
    r2_link = None
    for index in range(1, 9):
        r2_link = "r2-link" + str(index)
        input_dict_4 = {
            "r2": {
                "bgp": {
                    "address_family": {
                        "ipv4": {
                            "unicast": {
                                "neighbor": {
                                    "r1": {
                                        "dest_link": {
                                            r2_link: {
                                                "route_maps": [
                                                    {"name": "RMv4", "direction": "in"}
                                                ]
                                            },
                                        }
                                    }
                                }
                            }
                        },
                        "ipv6": {
                            "unicast": {
                                "neighbor": {
                                    "r1": {
                                        "dest_link": {
                                            r2_link: {
                                                "route_maps": [
                                                    {"name": "RMv6", "direction": "in"}
                                                ]
                                            },
                                        }
                                    }
                                }
                            }
                        },
                    }
                }
            }
        }
        result = create_router_bgp(tgen, topo, input_dict_4)
        assert result is True, "Testcase {} : Failed \n Error: {}".format(
            tc_name, result
        )

    step("After applying the route-map the routes are not expected in RIB ")
    r2_link = None
    for index in range(1, 9):
        r2_link = "r2-link" + str(index)
        ipv4_nxt_hop = topo["routers"]["r1"]["links"][r2_link]["ipv4"].split("/")[0]
        interface = topo["routers"]["r1"]["links"][r2_link]["interface"]
        ipv6_link_local_nxt_hop = get_frr_ipv6_linklocal(tgen, "r1", intf=interface)
        DEFAULT_ROUTE_NXT_HOP = {"ipv4": ipv4_nxt_hop, "ipv6": ipv6_link_local_nxt_hop}

        result = verify_rib_default_route(
            tgen,
            topo,
            dut="r2",
            routes=DEFAULT_ROUTES,
            expected_nexthop=DEFAULT_ROUTE_NXT_HOP,
            expected=False,
        )
        assert result is not True, "Testcase {} : Failed \n Error: {}".format(
            tc_name, result
        )

    write_test_footer(tc_name)


if __name__ == "__main__":
    args = ["-s"] + sys.argv[1:]
    sys.exit(pytest.main(args))
