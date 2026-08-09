//
// Copyright 2013 Ettus Research LLC
// Copyright 2018 Ettus Research, a National Instruments Company
//
// SPDX-License-Identifier: GPL-3.0-or-later
//

#include "b200_uart.hpp"
#include "b200_impl.hpp"
#include <uhd/exception.hpp>
#include <uhd/transport/bounded_buffer.hpp>
#include <uhd/transport/vrt_if_packet.hpp>
#include <uhd/types/time_spec.hpp>
#include <uhd/utils/byteswap.hpp>
#include <uhd/utils/log.hpp>
#include <chrono>

using namespace uhd;
using namespace uhd::transport;

struct b200_uart_impl : b200_uart
{
    b200_uart_impl(zero_copy_if::sptr xport, const uint32_t sid)
        : _xport(xport)
        , _sid(sid)
        , _count(0)
        , _baud_div(std::floor(B200_BUS_CLOCK_RATE / 38400 + 0.5))
        , _byte_queue(4096)
        , _line_queue(4096)
    {
        /*NOP*/
    }

    void send_char(const uint8_t ch)
    {
        managed_send_buffer::sptr buff = _xport->get_send_buff();
        UHD_ASSERT_THROW(bool(buff));

        vrt::if_packet_info_t packet_info;
        packet_info.link_type           = vrt::if_packet_info_t::LINK_TYPE_CHDR;
        packet_info.packet_type         = vrt::if_packet_info_t::PACKET_TYPE_CONTEXT;
        packet_info.num_payload_words32 = 2;
        packet_info.num_payload_bytes =
            packet_info.num_payload_words32 * sizeof(uint32_t);
        packet_info.packet_count = _count++;
        packet_info.sob          = false;
        packet_info.eob          = false;
        packet_info.sid          = _sid;
        packet_info.has_sid      = true;
        packet_info.has_cid      = false;
        packet_info.has_tsi      = false;
        packet_info.has_tsf      = false;
        packet_info.has_tlr      = false;

        uint32_t* packet_buff = buff->cast<uint32_t*>();
        vrt::if_hdr_pack_le(packet_buff, packet_info);
        packet_buff[packet_info.num_header_words32 + 0] = uhd::htowx(uint32_t(_baud_div));
        packet_buff[packet_info.num_header_words32 + 1] = uhd::htowx(uint32_t(ch));
        buff->commit(packet_info.num_packet_words32 * sizeof(uint32_t));
    }

    void write_uart(const std::string& buff) override
    {
        write_uart_bytes(byte_vector_t(buff.begin(), buff.end()));
    }

    void write_uart_bytes(const byte_vector_t& bytes) override
    {
        for (const uint8_t byte : bytes) {
            this->send_char(byte);
        }
    }

    std::string read_uart(double timeout) override
    {
        std::string line;
        _line_queue.pop_with_timed_wait(line, timeout);
        return line;
    }

    byte_vector_t read_uart_bytes(const size_t num_bytes, const double timeout) override
    {
        byte_vector_t bytes;
        bytes.reserve(num_bytes);
        if (num_bytes == 0) {
            return bytes;
        }

        const auto deadline = std::chrono::steady_clock::now()
                              + std::chrono::duration<double>(timeout);
        while (bytes.size() < num_bytes) {
            const double remaining = std::chrono::duration<double>(
                                         deadline - std::chrono::steady_clock::now())
                                         .count();
            if (remaining <= 0.0) {
                break;
            }
            uint8_t byte = 0;
            if (!_byte_queue.pop_with_timed_wait(byte, remaining)) {
                break;
            }
            bytes.push_back(byte);
        }

        return bytes;
    }

    void handle_uart_packet(managed_recv_buffer::sptr buff) override
    {
        const uint32_t* packet_buff = buff->cast<const uint32_t*>();
        vrt::if_packet_info_t packet_info;
        packet_info.link_type          = vrt::if_packet_info_t::LINK_TYPE_CHDR;
        packet_info.num_packet_words32 = buff->size() / sizeof(uint32_t);
        vrt::if_hdr_unpack_le(packet_buff, packet_info);
        const uint8_t byte = uint8_t(
            uhd::wtohx(packet_buff[packet_info.num_header_words32 + 1]) & 0xff);
        _byte_queue.push_with_pop_on_full(byte);
        const char ch = static_cast<char>(byte);
        _line += ch;
        if (ch == '\n') {
            _line_queue.push_with_pop_on_full(_line);
            _line.clear();
        }
    }

    const zero_copy_if::sptr _xport;
    const uint32_t _sid;
    size_t _count;
    size_t _baud_div;
    bounded_buffer<uint8_t> _byte_queue;
    bounded_buffer<std::string> _line_queue;
    std::string _line;
};


b200_uart::sptr b200_uart::make(zero_copy_if::sptr xport, const uint32_t sid)
{
    return b200_uart::sptr(new b200_uart_impl(xport, sid));
}
